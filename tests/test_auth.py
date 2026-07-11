"""Tests for src/auth.py — アカウント制の認証（ハッシュ・登録ゲート）。"""
import pytest

from src import auth, db


@pytest.fixture
def conn():
    c = db.get_conn(":memory:")
    db.init_db(c)          # SCHEMA に app_user が含まれる
    return c


# --------------------------------------------------------------------------- #
# パスワードハッシュ
# --------------------------------------------------------------------------- #
def test_hash_verify_roundtrip():
    h, s = auth.hash_password("s3cret-パス")
    assert auth.verify_password("s3cret-パス", h, s) is True


def test_verify_rejects_wrong_password():
    h, s = auth.hash_password("correct-horse")
    assert auth.verify_password("wrong", h, s) is False


def test_hash_is_salted_and_hex():
    h1, s1 = auth.hash_password("same-password")
    h2, s2 = auth.hash_password("same-password")
    assert s1 != s2 and h1 != h2          # 毎回ランダムソルト
    # 16進文字列であること
    int(h1, 16); int(s1, 16)


def test_verify_handles_bad_salt_gracefully():
    assert auth.verify_password("x", "deadbeef", "not-hex!") is False


# --------------------------------------------------------------------------- #
# email
# --------------------------------------------------------------------------- #
def test_normalize_email():
    assert auth.normalize_email("  Foo@Example.COM ") == "foo@example.com"


@pytest.mark.parametrize("email,ok", [
    ("a@b.co", True),
    ("user.name@example.co.jp", True),
    ("bad", False),
    ("no@domain", False),
    ("@no-local.com", False),
    ("spa ce@x.com", False),
    ("", False),
])
def test_is_valid_email(email, ok):
    assert auth.is_valid_email(email) is ok


# --------------------------------------------------------------------------- #
# 登録・認証
# --------------------------------------------------------------------------- #
def test_create_and_authenticate(conn):
    auth.create_user(conn, "admin@example.com", "password123")
    u = auth.authenticate(conn, "admin@example.com", "password123")
    assert u == {"email": "admin@example.com", "role": "admin"}


def test_login_is_case_insensitive_on_email(conn):
    auth.create_user(conn, "Mixed@Case.com", "password123")
    assert auth.authenticate(conn, "mixed@case.com", "password123") is not None


def test_create_duplicate_raises(conn):
    auth.create_user(conn, "dup@example.com", "password123")
    with pytest.raises(auth.AuthError, match="既に登録"):
        auth.create_user(conn, "dup@example.com", "password123")


def test_create_invalid_email_raises(conn):
    with pytest.raises(auth.AuthError, match="メールアドレス"):
        auth.create_user(conn, "not-an-email", "password123")


def test_create_short_password_raises(conn):
    with pytest.raises(auth.AuthError, match="8文字"):
        auth.create_user(conn, "a@b.com", "short")


def test_authenticate_wrong_password_returns_none(conn):
    auth.create_user(conn, "a@b.com", "password123")
    assert auth.authenticate(conn, "a@b.com", "nope") is None


def test_authenticate_unknown_user_returns_none(conn):
    assert auth.authenticate(conn, "ghost@b.com", "whatever") is None


def test_set_password_changes_login(conn):
    auth.create_user(conn, "a@b.com", "oldpassword")
    auth.set_password(conn, "a@b.com", "newpassword")
    assert auth.authenticate(conn, "a@b.com", "oldpassword") is None
    assert auth.authenticate(conn, "a@b.com", "newpassword") is not None


def test_set_password_too_short_raises(conn):
    auth.create_user(conn, "a@b.com", "oldpassword")
    with pytest.raises(auth.AuthError):
        auth.set_password(conn, "a@b.com", "x")


def test_list_delete_count_users(conn):
    assert auth.count_users(conn) == 0
    auth.create_user(conn, "one@b.com", "password123")
    auth.create_user(conn, "two@b.com", "password123")
    assert auth.count_users(conn) == 2
    assert auth.user_exists(conn, "one@b.com") is True
    emails = [u["email"] for u in auth.list_users(conn)]
    assert set(emails) == {"one@b.com", "two@b.com"}
    auth.delete_user(conn, "one@b.com")
    assert auth.user_exists(conn, "one@b.com") is False
    assert auth.count_users(conn) == 1


# --------------------------------------------------------------------------- #
# 登録ゲート（招待コード / 非常口）— env 経由
# --------------------------------------------------------------------------- #
def test_signup_code_gate(monkeypatch):
    monkeypatch.setenv("SIGNUP_CODE", "合言葉-2026")
    assert auth.signup_code() == "合言葉-2026"
    assert auth.check_signup_code("合言葉-2026") is True
    assert auth.check_signup_code("wrong") is False


def test_signup_code_unset_is_closed(monkeypatch):
    monkeypatch.delenv("SIGNUP_CODE", raising=False)
    # streamlit secrets が無い環境では空文字 → 常に False
    assert auth.check_signup_code("anything") is False


def test_admin_password_gate(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "マスター123")
    assert auth.check_admin_password("マスター123") is True
    assert auth.check_admin_password("マスター124") is False


def test_admin_password_unset_is_false(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert auth.check_admin_password("anything") is False


def test_ensure_users_table_standalone():
    """init_db を通さず ensure_users_table 単体でも動く。"""
    c = db.get_conn(":memory:")
    auth.ensure_users_table(c)
    auth.create_user(c, "solo@b.com", "password123")
    assert auth.authenticate(c, "solo@b.com", "password123") is not None
