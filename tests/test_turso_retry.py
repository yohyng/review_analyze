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
            sent.append(len(statements))      # 1リクエストに入った「文」の数
            for sql, params in statements:
                real(sql, params)

        def commit(self):
            conn.commit()

    assert db.set_topic_score_cache_bulk(_Pipelining(), rows) == 5
    assert len(sent) == 1, f"1リクエストにまとめること（{sent}）"
    assert sent[0] == 1, "5行は VALUES を並べて1文に畳むこと"
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


# --------------------------------------------------------------------------- #
# リトライの総時間に上限を設ける
#
#   1クエリのリトライは最大 7.5 秒の待ち。分析は数十クエリ撃つので、
#   Turso が継続的に不調だと待ちが積み上がり、分析全体が何分も止まる。
#   36クエリ全滅で待ちだけ 270 秒、HTTPタイムアウトを足すと10分級。
#   実際に「レポート生成中」のまま 600 秒止まる報告があった。
# --------------------------------------------------------------------------- #
def test_retry_budget_caps_the_total_wait(monkeypatch):
    """予算を使い切ったら、それ以降のクエリは粘らず即座に諦める。"""
    import time as _t

    slept = []
    monkeypatch.setattr(_t, "sleep", lambda s: slept.append(s))
    db.reset_retry_budget()

    # 502 を返し続けるセッションで、何クエリも撃つ
    for _ in range(50):
        s = _FakeSession(fail_times=99)
        with pytest.raises(requests.exceptions.HTTPError):
            db._post_with_retry(s, "http://x/v2/pipeline", {}, 15, retriable=True)

    total = sum(slept)
    assert total <= db._RETRY_BUDGET_S + 4.0, (
        f"リトライの待ちが {total:.0f} 秒まで積み上がった（上限 {db._RETRY_BUDGET_S}）"
    )
    assert db.retry_budget_left() == 0


def test_retry_budget_is_spent_before_it_runs_out(monkeypatch):
    """予算が残っているうちは、ちゃんとやり直す。"""
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda _s: None)
    db.reset_retry_budget()

    s = _FakeSession(fail_times=2)
    db._post_with_retry(s, "http://x/v2/pipeline", {}, 15, retriable=True)
    assert s.calls == 3
    assert 0 < db.retry_budget_left() < db._RETRY_BUDGET_S


def test_retry_budget_resets_per_analysis(monkeypatch):
    import time as _t

    monkeypatch.setattr(_t, "sleep", lambda _s: None)
    db.reset_retry_budget()
    s = _FakeSession(fail_times=99)
    with pytest.raises(requests.exceptions.HTTPError):
        db._post_with_retry(s, "http://x/v2/pipeline", {}, 15, retriable=True)
    assert db.retry_budget_left() < db._RETRY_BUDGET_S

    db.reset_retry_budget()
    assert db.retry_budget_left() == db._RETRY_BUDGET_S


def test_worker_resets_the_budget_at_the_start():
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    start = src.index("def _analysis_worker(")
    body = src[start:src.index("\ndef ", start + 1)]
    assert "db.reset_retry_budget()" in body


def test_running_screen_can_be_cancelled():
    """止まったときに待つしかない状態にしない。"""
    from pathlib import Path

    from src.ui import analysis_mode

    src = Path(analysis_mode.__file__).read_text(encoding="utf-8")
    assert 'key="an_cancel"' in src
    assert '_prog["cancelled"] = True' in src


# --------------------------------------------------------------------------- #
# 書き戻しの往復回数を行数から切り離す
#
#   以前は「1行 = 1文」を200文ずつ送っていたので、HTTP往復が 行数/200 に
#   比例した。実データの語彙書き戻しで 304 秒（約300往復）かかっていた。
#   VALUES を並べて1文に畳み、さらに数文を1リクエストに束ねる。
# --------------------------------------------------------------------------- #
class _CountingPipe:
    """execute_pipeline の呼び出し回数（＝HTTP往復）を数える。"""

    def __init__(self, real):
        self._real = real
        self.requests = 0
        self.statements = 0

    def execute(self, sql, *a):
        return self._real.execute(sql, *a)

    def execute_pipeline(self, statements):
        self.requests += 1
        self.statements += len(statements)
        for sql, params in statements:
            self._real.execute(sql, params)

    def commit(self):
        self._real.commit()


@pytest.mark.parametrize("n_rows,max_requests", [
    (500, 1), (2_000, 2), (10_000, 6), (60_000, 30),
])
def test_token_cache_flush_scales_far_better_than_one_request_per_200_rows(
        tmp_path, n_rows, max_requests):
    from src import db as _db

    conn = _db.get_conn(tmp_path / f"t{n_rows}.db")
    _db.init_db(conn)
    pipe = _CountingPipe(conn)
    items = {f"h{i:07d}": ["トークン", "の", "並び"] for i in range(n_rows)}

    assert _db.save_token_cache(pipe, items) == n_rows
    # 旧実装なら n_rows/200 回。少なくともその 1/5 以下に収まること。
    assert pipe.requests <= max_requests, (
        f"{n_rows:,}行で {pipe.requests} 往復（旧実装は {-(-n_rows//200)} 往復）"
    )
    assert conn.execute("SELECT COUNT(*) FROM token_cache").fetchone()[0] == n_rows


def test_folded_insert_writes_exactly_the_same_rows(tmp_path):
    """まとめ書きにしても中身が変わらないこと。"""
    from src import db as _db

    conn = _db.get_conn(tmp_path / "same.db")
    _db.init_db(conn)
    items = {f"h{i}": [f"語{i}", "と", "並び"] for i in range(1200)}
    _db.save_token_cache(conn, items)

    got = dict(conn.execute("SELECT h, tokens FROM token_cache").fetchall())
    assert len(got) == 1200
    for h, toks in items.items():
        assert got[h] == " ".join(toks)


def test_folded_insert_replaces_on_conflict(tmp_path):
    from src import db as _db

    conn = _db.get_conn(tmp_path / "up.db")
    _db.init_db(conn)
    _db.save_token_cache(conn, {"h1": ["古い"]})
    _db.save_token_cache(conn, {"h1": ["新しい", "値"]})
    row = conn.execute("SELECT tokens FROM token_cache WHERE h='h1'").fetchone()
    assert row[0] == "新しい 値"
    assert conn.execute("SELECT COUNT(*) FROM token_cache").fetchone()[0] == 1


@pytest.mark.parametrize("n_col", [1, 2, 5, 11])
def test_folded_insert_respects_the_bind_parameter_limit(n_col):
    """1文に渡すパラメータ数が SQLite の上限を超えないこと。

    列数が増えれば1文に入れる行数を減らす。ここを固定値にしていると、
    列の多いテーブル（topic_score_cache は5列）で上限を踏む。
    """
    from src import db as _db

    per = _db.rows_per_statement(n_col)
    assert per >= 1
    assert per * n_col <= _db._MAX_PARAMS
    assert _db._MAX_PARAMS <= 20_000


def test_write_failure_still_degrades_to_zero(tmp_path):
    from src import db as _db

    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

        def commit(self):
            pass

    assert _db.save_token_cache(_Broken(), {"h": ["a"]}) == 0
    assert _db.set_topic_score_cache_bulk(_Broken(), [(1, 10, "[]", 0.5, 3)]) == 0
