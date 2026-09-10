"""月間ダウンロード上限と、その帳簿の付け方。

KAIZODE の契約枠を月割りしたものを、**アプリ側で**数えて守る。
API 側に問い合わせる仕組みは無いので、ここが唯一の台帳になる。

台帳がずれる＝契約枠を超えて引く、なので、途中で落ちたときの挙動が肝心。
"""
from __future__ import annotations

import pytest

from src import db, kaizode


class _Client:
    """必要な口だけ持つフェイク。iter_reviews は無限に湧く。"""

    def __init__(self, datasets, per_dataset=1000, fail_on=None):
        self._datasets = datasets
        self._per = per_dataset
        self._fail_on = fail_on          # この dataset_id で例外を投げる
        self.fetched = []

    def list_datasets(self):
        return self._datasets

    def iter_reviews(self, dsid, published_since=None, limit=None):
        if self._fail_on == dsid:
            raise RuntimeError("ネットワーク断")
        for i in range(self._per):
            self.fetched.append(dsid)
            yield {
                "review_id": f"{dsid}-{i}", "rating": 5,
                "review": f"とても良い展示でした{i}。",
                "published_at": f"2025-04-{(i % 28) + 1:02d}T00:00:00Z",
                "publisher_name": f"u{i}", "place_name": f"施設{dsid}",
            }


def _ds(dsid, name=None):
    return {"dataset_id": dsid, "dataset_name": name or dsid,
            "status": kaizode.STATUS_DONE}


def _conn(tmp_path):
    conn = db.get_conn(tmp_path / "q.db")
    db.init_db(conn)
    return conn


# ── 既定値と保存 ─────────────────────────────────────────────────── #
def test_default_limit_is_ten_thousand(tmp_path):
    conn = _conn(tmp_path)
    assert kaizode.DEFAULT_MONTHLY_LIMIT == 10_000
    assert kaizode.monthly_limit(conn) == 10_000


def test_limit_is_stored_in_the_app_database(tmp_path):
    """API 側ではなくアプリのDBに持つ。再デプロイしても残る。"""
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 3_000)
    assert kaizode.monthly_limit(conn) == 3_000

    # 同じDBを開き直しても保持されている
    again = db.get_conn(tmp_path / "q.db")
    assert kaizode.monthly_limit(again) == 3_000


def test_limit_is_clamped(tmp_path):
    conn = _conn(tmp_path)
    assert kaizode.set_monthly_limit(conn, -5) == kaizode.MONTHLY_LIMIT_MIN
    assert kaizode.set_monthly_limit(conn, 10**9) == kaizode.MONTHLY_LIMIT_MAX
    assert kaizode.set_monthly_limit(conn, 0) == 0        # 0 で新規取得を止められる


def test_zero_limit_blocks_everything(tmp_path):
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 0)
    res = kaizode.sync_datasets(_Client([_ds("a")]), conn, log=lambda *_: None)
    assert res["limit_reached"] and res["fetched"] == 0
    assert kaizode.get_monthly_usage(conn) == 0


# ── 上限で打ち切る ───────────────────────────────────────────────── #
def test_download_stops_at_the_cap(tmp_path):
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 120)
    client = _Client([_ds("a"), _ds("b")], per_dataset=100)

    res = kaizode.sync_datasets(client, conn, log=lambda *_: None)
    assert res["fetched"] == 120, "残枠を超えて引いている"
    assert res["limit_reached"]
    assert kaizode.get_monthly_usage(conn) == 120
    assert kaizode.monthly_remaining(conn) == 0


def test_a_truncated_dataset_does_not_advance_last_sync(tmp_path):
    """打ち切られたデータセットは続きから取り直せること。"""
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 50)
    kaizode.sync_datasets(_Client([_ds("a")], per_dataset=100), conn,
                          log=lambda *_: None)
    assert kaizode.get_last_sync(conn, "a") is None, \
        "途中で止まったのに last_sync が進んでいる（残りが取れなくなる）"


# ── 途中で落ちても帳簿が残る（今回の修正）────────────────────────── #
def test_usage_survives_a_crash_partway(tmp_path):
    """引いた件数は、その場で帳簿に付けること。

    以前は関数の最後でまとめて加算していたので、2つ目のデータセットで
    落ちると1つ目のぶんが帳簿から消えていた。契約枠は「引いた時点」で
    減るので、台帳が実使用より小さくなる＝上限を超えて引ける。
    """
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 10_000)
    client = _Client([_ds("a"), _ds("b")], per_dataset=100, fail_on="b")

    with pytest.raises(RuntimeError):
        kaizode.sync_datasets(client, conn, log=lambda *_: None)

    assert kaizode.get_monthly_usage(conn) == 100, \
        "落ちる前に引いた100件が帳簿に残っていない"
    assert kaizode.monthly_remaining(conn) == 9_900


def test_usage_is_not_double_counted(tmp_path):
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 10_000)
    client = _Client([_ds("a"), _ds("b")], per_dataset=30)
    res = kaizode.sync_datasets(client, conn, log=lambda *_: None)
    assert res["fetched"] == 60
    assert kaizode.get_monthly_usage(conn) == 60, "二重に加算されている"
    assert res["monthly_used"] == 60


def test_usage_accumulates_across_runs(tmp_path):
    conn = _conn(tmp_path)
    kaizode.set_monthly_limit(conn, 10_000)
    for _ in range(3):
        kaizode.sync_datasets(_Client([_ds("a")], per_dataset=10), conn,
                              log=lambda *_: None)
    assert kaizode.get_monthly_usage(conn) == 30


def test_usage_is_per_month(tmp_path):
    conn = _conn(tmp_path)
    kaizode.add_monthly_usage(conn, 500, "2026-08")
    kaizode.add_monthly_usage(conn, 200, "2026-09")
    assert kaizode.get_monthly_usage(conn, "2026-08") == 500
    assert kaizode.get_monthly_usage(conn, "2026-09") == 200
    assert kaizode.monthly_remaining(conn, "2026-09", 10_000) == 9_800


# ── 差分同期の記録（枠を焼かないため）──────────────────────────── #
def test_last_sync_is_written_in_one_statement(tmp_path):
    """DELETE → INSERT だと Turso で間に失敗の窓が開く。

    記録が消えると次回は全件再取得になり、新規0件のまま月枠だけ焼く。
    8,000件のデータセットなら1回で月枠の8割が飛ぶ。
    """
    import inspect
    src = inspect.getsource(kaizode.set_last_sync)
    assert "DELETE FROM kaizode_sync" not in src, \
        "DELETE→INSERT に戻っている（Turso では非アトミック）"
    assert "INSERT OR REPLACE" in src


def test_last_sync_round_trips(tmp_path):
    conn = _conn(tmp_path)
    kaizode.set_last_sync(conn, "a", "ds-a", "2025-04-01T00:00:00")
    assert kaizode.get_last_sync(conn, "a") == "2025-04-01T00:00:00"
    # 上書きしても1行のまま
    kaizode.set_last_sync(conn, "a", "ds-a", "2025-05-01T00:00:00")
    assert kaizode.get_last_sync(conn, "a") == "2025-05-01T00:00:00"
    n = conn.execute("SELECT COUNT(*) FROM kaizode_sync WHERE dataset_id='a'"
                     ).fetchone()[0]
    assert n == 1
