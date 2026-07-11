"""ユーザー認証（メールアドレス＋パスワードのアカウント制）。

方針:
  * パスワードは pbkdf2_hmac(SHA-256) で **ハッシュ化して保存**（平文は持たない）。
  * 新規登録は招待コード（SIGNUP_CODE）を知っている人だけが行える＝
    URL を知っているだけでは管理者になれない「登録ゲート」。
  * ADMIN_PASSWORD は「最初の1人を作る／ロックアウト回避」用の非常口として併存。

SIGNUP_CODE / ADMIN_PASSWORD は環境変数または Streamlit secrets から読む。
テーブル app_user は db.SCHEMA 側で作成される（init_db 済み前提）。単体テストでは
ensure_users_table(conn) を呼べば自前で作れる。
"""
from __future__ import annotations

import binascii
import hashlib
import hmac
import os
import re
from datetime import datetime, timezone
from typing import Optional

# pbkdf2 パラメータ。Streamlit Cloud の CPU でも 1 回 ~50-100ms 程度。
_ALGO = "sha256"
_ITERATIONS = 200_000
_SALT_BYTES = 16
_MIN_PASSWORD_LEN = 8

USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    email         TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TEXT NOT NULL
)
"""

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """入力不備・重複など、ユーザーに見せてよい登録/認証エラー。"""


# --------------------------------------------------------------------------- #
# secrets / env
# --------------------------------------------------------------------------- #
def _secret(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        try:
            import streamlit as st  # noqa: PLC0415
            val = st.secrets.get(key, "") or ""
        except Exception:
            val = ""
    return val or ""


def signup_code() -> str:
    """登録に必要な招待コード（未設定なら空文字＝登録は無効）。"""
    return _secret("SIGNUP_CODE")


def check_signup_code(provided: str) -> bool:
    """招待コードの一致を定数時間比較で検証。未設定時は常に False。"""
    code = signup_code()
    if not code:
        return False
    return hmac.compare_digest((provided or "").encode("utf-8"), code.encode("utf-8"))


def admin_password() -> str:
    """非常口のマスターパスワード（未設定なら空文字）。"""
    return _secret("ADMIN_PASSWORD")


def check_admin_password(provided: str) -> bool:
    """非常口パスワードの一致を定数時間比較で検証。未設定時は常に False。"""
    pw = admin_password()
    if not pw:
        return False
    return hmac.compare_digest((provided or "").encode("utf-8"), pw.encode("utf-8"))


# --------------------------------------------------------------------------- #
# パスワードハッシュ
# --------------------------------------------------------------------------- #
def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    """(password_hash_hex, salt_hex) を返す。salt 省略時はランダム生成。"""
    if salt is None:
        salt = os.urandom(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(_ALGO, (password or "").encode("utf-8"), salt, _ITERATIONS)
    return binascii.hexlify(dk).decode("ascii"), binascii.hexlify(salt).decode("ascii")


def verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    """保存済みハッシュ/ソルトに対してパスワードを検証（定数時間比較）。"""
    try:
        salt = binascii.unhexlify(salt_hex)
    except (binascii.Error, ValueError, TypeError):
        return False
    calc, _ = hash_password(password or "", salt)
    return hmac.compare_digest(calc, password_hash or "")


# --------------------------------------------------------------------------- #
# email
# --------------------------------------------------------------------------- #
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


# --------------------------------------------------------------------------- #
# users テーブル
# --------------------------------------------------------------------------- #
def ensure_users_table(conn) -> None:
    """app_user テーブルを作成（IF NOT EXISTS）。db.init_db 済みなら不要だが、
    テストや古い DB のために安全側で用意。"""
    conn.execute(USER_SCHEMA.strip())
    conn.commit()


def count_users(conn) -> int:
    row = conn.execute("SELECT COUNT(*) FROM app_user").fetchone()
    return int(row[0]) if row else 0


def user_exists(conn, email: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM app_user WHERE email = ?", (normalize_email(email),)
    ).fetchone()
    return row is not None


def create_user(conn, email: str, password: str, role: str = "admin") -> dict:
    """新規ユーザーを作成。入力不備・重複は AuthError。成功時は user dict。"""
    email = normalize_email(email)
    if not is_valid_email(email):
        raise AuthError("メールアドレスの形式が正しくありません。")
    if len(password or "") < _MIN_PASSWORD_LEN:
        raise AuthError(f"パスワードは{_MIN_PASSWORD_LEN}文字以上にしてください。")
    if user_exists(conn, email):
        raise AuthError("このメールアドレスは既に登録されています。")
    h, s = hash_password(password)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO app_user(email, password_hash, salt, role, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (email, h, s, role, ts),
    )
    conn.commit()
    return {"email": email, "role": role, "created_at": ts}


def authenticate(conn, email: str, password: str) -> Optional[dict]:
    """メール＋パスワードを検証。成功時 user dict、失敗時 None。"""
    email = normalize_email(email)
    row = conn.execute(
        "SELECT email, password_hash, salt, role FROM app_user WHERE email = ?",
        (email,),
    ).fetchone()
    if not row:
        return None
    if verify_password(password or "", row[1], row[2]):
        return {"email": row[0], "role": row[3]}
    return None


def set_password(conn, email: str, new_password: str) -> None:
    """既存ユーザーのパスワードを再設定（新しいソルトで再ハッシュ）。"""
    email = normalize_email(email)
    if len(new_password or "") < _MIN_PASSWORD_LEN:
        raise AuthError(f"パスワードは{_MIN_PASSWORD_LEN}文字以上にしてください。")
    if not user_exists(conn, email):
        raise AuthError("ユーザーが見つかりません。")
    h, s = hash_password(new_password)
    conn.execute(
        "UPDATE app_user SET password_hash = ?, salt = ? WHERE email = ?",
        (h, s, email),
    )
    conn.commit()


def list_users(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT email, role, created_at FROM app_user ORDER BY created_at, email"
    ).fetchall()
    return [{"email": r[0], "role": r[1], "created_at": r[2]} for r in rows]


def delete_user(conn, email: str) -> None:
    conn.execute("DELETE FROM app_user WHERE email = ?", (normalize_email(email),))
    conn.commit()
