"""Turso（HTTP v2/pipeline）の一時障害に対する耐性のテスト。

背景:
  Turso は 1クエリ = 1 HTTPリクエスト。分析は施設数ぶんクエリを撃つので、
  途中で1回でもゲートウェイが 502 を返すと分析全体が落ちていた。

    requests.exceptions.HTTPError: 502 Server Error: Bad Gateway for url:
      https://....turso.io/v2/pipeline
      （db.get_topic_score_cache のループ中に発生）

  → ゲートウェイ由来の 5xx / 接続断だけを指数バックオフでやり直す。
    ただし「もう一度送っても結果が変わらない」文に限る。素の INSERT INTO を
    やり直すと、届いていた場合に行が二重に入る。
"""
from __future__ import annotations

import pytest
import requests

from src import db


# --------------------------------------------------------------------------- #
# どの文をやり直してよいか
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sql", [
    "SELECT * FROM facility",
    "  select 1 ",
    "PRAGMA table_info(review)",
    "CREATE TABLE IF NOT EXISTS x(a)",
    "UPDATE facility SET name = ? WHERE id = ?",
    "DELETE FROM review WHERE id = ?",
    "INSERT OR REPLACE INTO token_cache(h, tokens) VALUES (?, ?)",
    "INSERT OR IGNORE INTO score(facility_id) VALUES (?)",
])
def test_idempotent_statements_are_retriable(sql):
    assert db._is_retriable_sql(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO review(facility_id, text) VALUES (?, ?)",
    "insert into facility(name) values (?)",
    "INSERT INTO facility_photo(facility_id, image) VALUES (?, ?)",
])
def test_plain_inserts_are_not_retried(sql):
    """502 は『届かなかった』とも『届いたが応答が消えた』とも取れる。
    素の INSERT をやり直すと行が二重に入るので、やり直してはいけない。"""
    assert not db._is_retriable_sql(sql)


# --------------------------------------------------------------------------- #
# 何をやり直すか
# --------------------------------------------------------------------------- #
def _http_error(status: int) -> requests.exceptions.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    return requests.exceptions.HTTPError(f"{status}", response=resp)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_gateway_errors_are_transient(status):
    assert db._should_retry(_http_error(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_client_errors_are_not_transient(status):
    """SQLが悪い・認証が切れている類は、やり直しても同じ結果になる。"""
    assert not db._should_retry(_http_error(status))


def test_connection_problems_are_transient():
    assert db._should_retry(requests.exceptions.ConnectionError("reset"))
    assert db._should_retry(requests.exceptions.Timeout("timeout"))
    assert not db._should_retry(ValueError("something else"))


# --------------------------------------------------------------------------- #
# 実際にやり直すか
# --------------------------------------------------------------------------- #
class _FakeSession:
    """指定回数だけ失敗し、その後成功するセッション。"""

    def __init__(self, fail_times: int, status: int = 502):
        self.fail_times = fail_times
        self.status = status
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        resp = requests.Response()
        resp.status_code = self.status if self.calls <= self.fail_times else 200
        resp._content = b'{"results":[]}'
        return resp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """バックオフの待ちでテストを遅くしない。"""
    import time
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_retries_until_it_succeeds():
    s = _FakeSession(fail_times=2)
    db._post_with_retry(s, "http://x/v2/pipeline", {}, 30, retriable=True)
    assert s.calls == 3          # 502, 502, 200


def test_gives_up_after_the_limit():
    s = _FakeSession(fail_times=99)
    with pytest.raises(requests.exceptions.HTTPError):
        db._post_with_retry(s, "http://x/v2/pipeline", {}, 30, retriable=True)
    assert s.calls == db._RETRY_MAX + 1


def test_does_not_retry_when_the_statement_is_unsafe_to_repeat():
    s = _FakeSession(fail_times=99)
    with pytest.raises(requests.exceptions.HTTPError):
        db._post_with_retry(s, "http://x/v2/pipeline", {}, 30, retriable=False)
    assert s.calls == 1


def test_does_not_retry_a_client_error():
    s = _FakeSession(fail_times=99, status=400)
    with pytest.raises(requests.exceptions.HTTPError):
        db._post_with_retry(s, "http://x/v2/pipeline", {}, 30, retriable=True)
    assert s.calls == 1


# --------------------------------------------------------------------------- #
# 往復回数そのものを減らす
# --------------------------------------------------------------------------- #
def test_topic_score_cache_is_read_in_one_query(tmp_path):
    """施設ごとに引くと施設数ぶん往復し、その回数だけ502を踏む機会が増える。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    want = {}
    for i in range(1, 6):
        fid = db.upsert_facility(conn, f"施設{i}")
        db.set_topic_score_cache(conn, fid, 10 * i, f'[{{"n":{i}}}]', 0.5 + i, 30 * i)
        want[(fid, 10 * i)] = i

    calls = []
    real = conn.execute
    conn_proxy = type("P", (), {
        "execute": lambda _s, sql, *a: (calls.append(sql) or real(sql, *a)),
    })()

    bulk = db.get_topic_score_cache_bulk(conn_proxy)
    assert len(calls) == 1, f"1クエリで読むこと（{len(calls)}回発行された）"
    assert set(bulk) == set(want)
    for key, i in want.items():
        assert bulk[key]["overall_score"] == pytest.approx(0.5 + i)
        assert bulk[key]["n_sentences"] == 30 * i
        # 1件ずつ引いた結果と一致すること
        assert bulk[key] == db.get_topic_score_cache(conn, key[0], key[1])


def test_bulk_cache_read_degrades_to_empty_on_failure():
    """キャッシュは高速化のためのもの。読めなければ再計算に落ちればよい。"""
    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

    assert db.get_topic_score_cache_bulk(_Broken()) == {}


def test_worker_does_not_query_the_cache_per_facility():
    """施設ループの中で get_topic_score_cache を呼ばないこと（往復が施設数ぶん増える）。"""
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    start = src.index("def _analysis_worker(")
    body = src[start:src.index("\ndef ", start + 1)]
    assert "db.get_topic_score_cache(" not in body
    assert "db.get_topic_score_cache_bulk(" in body


def test_review_texts_are_read_in_one_query(tmp_path):
    """未計算の施設ぶんの本文も1クエリで読む（施設ごとに引くと往復が施設数ぶん）。"""
    from src import review_csv

    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    names = [f"施設{i}" for i in range(4)]
    for fi, name in enumerate(names):
        fid = db.upsert_facility(conn, name)
        db.insert_reviews(conn, fid, [
            review_csv.ParsedReview(
                review_id=f"{fi}-{j}", rating=4, text=f"{name}の口コミ{j}",
                review_date="2025-01-01T00:00:00Z", reviewer_name="u",
                local_guide=False, likes=None, owner_response="",
                owner_response_date="", subscores=[],
            )
            for j in range(3)
        ])
    conn.commit()

    calls = []
    real = conn.execute
    proxy = type("P", (), {
        "execute": lambda _s, sql, *a: (calls.append(sql) or real(sql, *a)),
    })()

    got = db.review_texts_by_facility(proxy, names)
    assert len(calls) == 1, f"1クエリで読むこと（{len(calls)}回発行された）"
    assert set(got) == set(names)
    for n in names:
        assert sorted(got[n]) == sorted(f"{n}の口コミ{j}" for j in range(3))


def test_review_texts_handles_an_empty_request(tmp_path):
    """全施設がキャッシュ済みなら、そもそもクエリを撃たない。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)

    calls = []
    proxy = type("P", (), {"execute": lambda _s, *a: calls.append(a)})()
    assert db.review_texts_by_facility(proxy, []) == {}
    assert calls == []


def test_batched_scores_match_the_per_facility_path(tmp_path):
    """まとめ読みに変えてもスコアが変わらないこと。"""
    from src import review_csv, topic_score

    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    texts = [
        "スタッフの対応が丁寧で気持ちよく過ごせました。展示も見応えがあります。",
        "料金のわりに展示が少なく物足りない。混雑していて疲れました。",
        "館内が清潔で快適でした。案内表示も分かりやすいです。",
    ]
    fid = db.upsert_facility(conn, "対象館")
    db.insert_reviews(conn, fid, [
        review_csv.ParsedReview(
            review_id=f"r{j}", rating=4, text=t,
            review_date="2025-01-01T00:00:00Z", reviewer_name="u",
            local_guide=False, likes=None, owner_response="",
            owner_response_date="", subscores=[],
        )
        for j, t in enumerate(texts)
    ])
    conn.commit()

    per_facility = topic_score.analyze_facility(conn, "対象館")
    batched = topic_score.analyze_reviews(
        db.review_texts_by_facility(conn, ["対象館"])["対象館"]
    )
    assert batched.overall_score == pytest.approx(per_facility.overall_score)
    assert [t.name for t in batched.topics] == [t.name for t in per_facility.topics]
    for a, b in zip(batched.topics, per_facility.topics):
        assert a.sentiment == pytest.approx(b.sentiment)


def test_topic_score_cache_writes_are_batched(tmp_path):
    """施設ごとに書くと施設数ぶん往復する。まとめ送りに載ること。"""
    conn = db.get_conn(tmp_path / "t.db")
    db.init_db(conn)
    fids = [db.upsert_facility(conn, f"施設{i}") for i in range(5)]
    rows = [(f, 10, '[{"n":1}]', 0.5, 30) for f in fids]

    sent = []
    real = conn.execute

    class _Pipelining:
        def execute(self, sql, *a):
            return real(sql, *a)

        def execute_pipeline(self, statements):
            sent.append(len(statements))
            for sql, params in statements:
                real(sql, params)

        def commit(self):
            conn.commit()

    assert db.set_topic_score_cache_bulk(_Pipelining(), rows) == 5
    assert sent == [5], f"1リクエストにまとめること（{sent}）"
    got = db.get_topic_score_cache_bulk(conn)
    assert set(got) == {(f, 10) for f in fids}


def test_cache_write_failure_does_not_break_the_analysis(tmp_path):
    """キャッシュは高速化のためのもの。書けなくても分析は続けられること。"""
    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")
        def commit(self):
            pass

    assert db.set_topic_score_cache_bulk(_Broken(), [(1, 10, "[]", 0.5, 3)]) == 0
    assert db.set_topic_score_cache_bulk(_Broken(), []) == 0


def test_worker_does_not_write_the_cache_per_facility():
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    start = src.index("def _analysis_worker(")
    body = src[start:src.index("\ndef ", start + 1)]
    assert "db.set_topic_score_cache(" not in body
    assert "db.set_topic_score_cache_bulk(" in body
