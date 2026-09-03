"""KAIZODE の新規取得を月1万件で頭打ちにする設定のテスト。

カウントは「新規に取り込めた口コミ件数」（重複は数えない）。
上限は DB の app_setting に持つので、管理画面から変えられ、
アプリを再起動しても残る。
"""
from __future__ import annotations

import pytest
import requests

from src import db, kaizode


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "t.db")
    db.init_db(c)
    return c


# --------------------------------------------------------------------------- #
# 既定値と設定
# --------------------------------------------------------------------------- #
def test_default_limit_is_ten_thousand_per_month(conn):
    assert kaizode.DEFAULT_MONTHLY_LIMIT == 10_000
    assert kaizode.monthly_limit(conn) == 10_000


def test_limit_can_be_changed_and_persists(conn, tmp_path):
    assert kaizode.set_monthly_limit(conn, 3000) == 3000
    assert kaizode.monthly_limit(conn) == 3000
    # 別の接続（＝再起動相当）から読んでも残っている
    other = db.get_conn(tmp_path / "t.db")
    assert kaizode.monthly_limit(other) == 3000


def test_limit_is_clamped_to_a_sane_range(conn):
    assert kaizode.set_monthly_limit(conn, -50) == kaizode.MONTHLY_LIMIT_MIN
    assert kaizode.set_monthly_limit(conn, 10 ** 9) == kaizode.MONTHLY_LIMIT_MAX


def test_zero_limit_stops_new_downloads(conn):
    kaizode.set_monthly_limit(conn, 0)
    assert kaizode.monthly_limit(conn) == 0
    assert kaizode.monthly_remaining(conn) == 0


def test_a_broken_setting_falls_back_to_the_default(conn):
    db.set_setting(conn, kaizode.SETTING_MONTHLY_LIMIT, "たくさん")
    assert kaizode.monthly_limit(conn) == kaizode.DEFAULT_MONTHLY_LIMIT


def test_limit_is_read_from_the_db_every_time(conn):
    """管理画面で変えた直後から効くこと（再起動が要る、にしない）。"""
    assert kaizode.monthly_limit(conn) == 10_000
    kaizode.set_monthly_limit(conn, 500)
    assert kaizode.monthly_limit(conn) == 500


# --------------------------------------------------------------------------- #
# 月次カウントと残枠
# --------------------------------------------------------------------------- #
def test_usage_accumulates_within_the_month(conn):
    assert kaizode.get_monthly_usage(conn) == 0
    kaizode.add_monthly_usage(conn, 120)
    kaizode.add_monthly_usage(conn, 80)
    assert kaizode.get_monthly_usage(conn) == 200
    assert kaizode.monthly_remaining(conn) == 10_000 - 200


def test_usage_is_counted_per_month(conn):
    kaizode.add_monthly_usage(conn, 300, month="2026-01")
    kaizode.add_monthly_usage(conn, 50, month="2026-02")
    assert kaizode.get_monthly_usage(conn, "2026-01") == 300
    assert kaizode.get_monthly_usage(conn, "2026-02") == 50
    # 月が変われば枠は戻る
    assert kaizode.monthly_remaining(conn, "2026-02") == 10_000 - 50


def test_remaining_never_goes_negative(conn):
    kaizode.set_monthly_limit(conn, 100)
    kaizode.add_monthly_usage(conn, 250)
    assert kaizode.monthly_remaining(conn) == 0


def test_zero_or_negative_usage_is_ignored(conn):
    kaizode.add_monthly_usage(conn, 0)
    kaizode.add_monthly_usage(conn, -5)
    assert kaizode.get_monthly_usage(conn) == 0


# --------------------------------------------------------------------------- #
# 実際に取り込みを止める
# --------------------------------------------------------------------------- #
class _FakeClient:
    """DONE のデータセットを1つ持ち、レビューを無限に返すクライアント。"""

    def __init__(self, n_available: int = 10_000):
        self.n = n_available
        self.asked = []

    def list_datasets(self):
        return [{"dataset_id": "ds1", "dataset_name": "テスト館",
                 "status": kaizode.STATUS_DONE}]

    def iter_reviews(self, dsid, published_since=None, limit=None):
        """API と同じく生の dict を返す（sync_datasets 側で ParsedReview に変換する）。"""
        self.asked.append(dsid)
        for i in range(self.n):
            yield {
                "review_id": f"r{i}", "rating": 4, "text": f"口コミ{i}",
                "published_at": "2026-01-01T00:00:00Z", "reviewer_name": "u",
                "review_target_name": "テスト館",
            }


def test_sync_stops_at_the_configured_limit(conn):
    kaizode.set_monthly_limit(conn, 25)
    res = kaizode.sync_datasets(_FakeClient(), conn, log=lambda *_a: None)

    assert res["monthly_limit"] == 25
    assert res["inserted"] <= 25, "上限を超えて取り込んでいる"
    assert kaizode.get_monthly_usage(conn) <= 25
    assert res.get("limit_reached")


def test_sync_refuses_once_the_month_is_exhausted(conn):
    kaizode.set_monthly_limit(conn, 10)
    kaizode.add_monthly_usage(conn, 10)
    c = _FakeClient()
    res = kaizode.sync_datasets(c, conn, log=lambda *_a: None)

    assert res["inserted"] == 0 and res["limit_reached"]
    assert res["monthly_limit"] == 10
    assert c.asked == [], "枠が無いのに取得しにいっている"


def test_sync_with_a_zero_limit_downloads_nothing(conn):
    kaizode.set_monthly_limit(conn, 0)
    c = _FakeClient()
    res = kaizode.sync_datasets(c, conn, log=lambda *_a: None)
    assert res["inserted"] == 0 and c.asked == []


def test_sync_reports_the_configured_limit_not_the_constant(conn):
    kaizode.set_monthly_limit(conn, 777)
    res = kaizode.sync_datasets(_FakeClient(n_available=5), conn,
                                log=lambda *_a: None)
    assert res["monthly_limit"] == 777


# --------------------------------------------------------------------------- #
# 画面側
# --------------------------------------------------------------------------- #
def test_admin_page_offers_the_limit_setting():
    from pathlib import Path

    from src.ui import admin_mode

    src = Path(admin_mode.__file__).read_text(encoding="utf-8")
    assert "kaizode.monthly_limit(conn)" in src
    assert "kaizode.set_monthly_limit(conn" in src
    assert 'key="kz_limit_input"' in src
    assert "kaizode.MONTHLY_LIMIT" not in src.replace(
        "kaizode.MONTHLY_LIMIT_MIN", "").replace("kaizode.MONTHLY_LIMIT_MAX", "")


def test_no_screen_reads_the_stale_constant():
    """定数を直接読むと、管理画面で変えた値が反映されない。"""
    from pathlib import Path

    for mod in ("analysis_mode", "admin_mode"):
        src = Path(f"src/ui/{mod}.py").read_text(encoding="utf-8")
        stripped = src.replace("kaizode.MONTHLY_LIMIT_MIN", "").replace(
            "kaizode.MONTHLY_LIMIT_MAX", "")
        assert "kaizode.MONTHLY_LIMIT" not in stripped, mod
