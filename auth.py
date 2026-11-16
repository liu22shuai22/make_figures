"""用户账号与登录会话：sqlite 存储，pbkdf2 加盐哈希。

与 token_usage.py 同一套约定：独立 sqlite 文件、短连接、模块加载时建表。
密码不存明文；会话 token 随机生成，30 天有效，退出即删。
"""
import hashlib
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).with_name("auth.sqlite3")
PBKDF2_ITERATIONS = 240_000
SESSION_DAYS = 30

USERNAME_MIN, USERNAME_MAX = 2, 24
PASSWORD_MIN, PASSWORD_MAX = 6, 64
EMAIL_MAX = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """业务错误，message 直接面向用户，api 层原样返回。"""


class UsernameTakenError(AuthError):
    def __init__(self):
        super().__init__("这个用户名已被注册，换一个试试")


class EmailTakenError(AuthError):
    def __init__(self):
        super().__init__("这个邮箱已被注册，换一个试试")


class InvalidEmailError(AuthError):
    def __init__(self):
        super().__init__("邮箱格式不正确")


class CodeRateError(AuthError):
    def __init__(self):
        super().__init__("验证码刚发过，请 60 秒后再试")


class BadCodeError(AuthError):
    def __init__(self):
        super().__init__("验证码不正确或已过期")


class MailNotConfiguredError(AuthError):
    def __init__(self):
        super().__init__("邮件服务还没配好，暂时发不出验证码")


class MailDeliveryError(AuthError):
    def __init__(self, message="验证码邮件没有发出去，请稍后再试"):
        super().__init__(message)


class BadCredentialsError(AuthError):
    def __init__(self):
        super().__init__("用户名或密码不正确")


class NotAuthenticatedError(AuthError):
    def __init__(self):
        super().__init__("登录状态已失效，请重新登录")


def _connect():
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    return db


def _init_table():
    with closing(_connect()) as db, db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None:
            db.execute(
                "CREATE TABLE users ("
                " username TEXT PRIMARY KEY,"
                " password_hash TEXT NOT NULL,"
                " salt TEXT NOT NULL,"
                " created_at TEXT NOT NULL)"
            )
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone() is None:
            db.execute(
                "CREATE TABLE sessions ("
                " token TEXT PRIMARY KEY,"
                " username TEXT NOT NULL,"
                " created_at TEXT NOT NULL,"
                " expires_at TEXT NOT NULL)"
            )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "email" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email) WHERE email IS NOT NULL"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS email_codes ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " email TEXT NOT NULL,"
            " code_hash TEXT NOT NULL,"
            " created_at TEXT NOT NULL,"
            " expires_at TEXT NOT NULL,"
            " attempts INTEGER NOT NULL)"
        )


_init_table()


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS
    )
    return digest.hex()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    """去掉首尾空白并转成小写。格式不对时抛 InvalidEmailError。"""
    cleaned = email.strip().lower()
    if not cleaned or len(cleaned) > EMAIL_MAX or _EMAIL_RE.fullmatch(cleaned) is None:
        raise InvalidEmailError
    return cleaned


def _code_hash(email: str, code: str) -> str:
    return hashlib.sha256(f"{email}:{code}".encode("utf-8")).hexdigest()


def issue_email_code(email: str) -> None:
    """生成 6 位验证码，先发出邮件，再记入数据库。10 分钟内有效。"""
    from mailer import send_verification_code

    email = normalize_email(email)
    now = _now()
    with closing(_connect()) as db:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None:
            raise EmailTakenError
        last = db.execute(
            "SELECT created_at FROM email_codes WHERE email = ? ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
    if last is not None and last["created_at"] > (now - timedelta(seconds=60)).isoformat(timespec="seconds"):
        raise CodeRateError
    code = f"{secrets.randbelow(1_000_000):06d}"
    send_verification_code(email, code)
    expires = (now + timedelta(minutes=10)).isoformat(timespec="seconds")
    with closing(_connect()) as db, db:
        db.execute(
            "INSERT INTO email_codes (email, code_hash, created_at, expires_at, attempts) "
            "VALUES (?, ?, ?, ?, 0)",
            (email, _code_hash(email, code), now.isoformat(timespec="seconds"), expires),
        )


def _consume_code(db: sqlite3.Connection, email: str, code: str) -> None:
    row = db.execute(
        "SELECT id, code_hash, expires_at, attempts FROM email_codes WHERE email = ? ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchone()
    now = _now().isoformat(timespec="seconds")
    if row is None or row["expires_at"] < now or row["attempts"] >= 5 or not re.fullmatch(r"\d{6}", code or ""):
        raise BadCodeError
    if not secrets.compare_digest(_code_hash(email, code), row["code_hash"]):
        db.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        db.commit()
        raise BadCodeError
    db.execute("DELETE FROM email_codes WHERE email = ?", (email,))


def create_user(username: str, password: str, email: str, code: str) -> str:
    """校验验证码后，在同一个事务内创建用户和会话。"""
    email = normalize_email(email)
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    created_at = _now().isoformat(timespec="seconds")
    with closing(_connect()) as db, db:
        _consume_code(db, email, code)
        taken = db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
        if taken is not None:
            raise EmailTakenError
        inserted = db.execute(
            "INSERT INTO users (username, password_hash, salt, created_at, email) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(username) DO NOTHING",
            (username, password_hash, salt, created_at, email),
        )
        if inserted.rowcount == 0:
            raise UsernameTakenError
        return _insert_session(db, username)


def verify_login(username: str, password: str) -> None:
    """校验用户名与密码。失败抛 BadCredentialsError（不区分哪一项错，避免用户名枚举）。"""
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None or _hash_password(password, row["salt"]) != row["password_hash"]:
        raise BadCredentialsError


def open_session(username: str) -> str:
    """登录成功后发放会话 token。"""
    with closing(_connect()) as db, db:
        return _insert_session(db, username)


def _insert_session(db: sqlite3.Connection, username: str) -> str:
    token = secrets.token_hex(32)
    now = _now()
    expires = (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO sessions (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, username, now.isoformat(timespec="seconds"), expires),
    )
    return token


def session_username(token: str) -> str:
    """用 token 查当前用户。无效或过期抛 NotAuthenticatedError。"""
    if not token:
        raise NotAuthenticatedError
    with closing(_connect()) as db:
        row = db.execute("SELECT username, expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
    if row is None or row["expires_at"] < _now().isoformat(timespec="seconds"):
        raise NotAuthenticatedError
    return row["username"]


def close_session(token: str) -> None:
    """退出登录：删除该会话。"""
    with closing(_connect()) as db, db:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))

