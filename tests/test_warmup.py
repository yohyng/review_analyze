"""事前計算を分割して回せること・途中で止めても進んだぶんが残ることのテスト。

背景:
  以前は全施設を1回のスクリプト実行でやり切る造りで、
  - Streamlit Cloud の実行時間・WebSocket が先に切れると全部やり直し
  - 形態素解析（一番重い）の結果を最後にまとめて書いていたので、
    落ちるとそこまでの解析がまるごと消える
  - 施設ごとにキャッシュを読み書きしていて、Turso では施設数ぶんの HTTP 往復
  という壊れ方をしていた。

  → 1バッチ = 数施設に切り、**バッチごとに必ず書き切る**。
    次に走らせるときは未計算の施設だけが残る、という取り決めを固定する。
"""
from __future__ import annotations

import pytest
import requests

from src import db, review_csv, text_analysis, topic_score, warmup

_TEXTS = [
    "スタッフの対応がとても丁寧で気持ちよく過ごせました。展示も見応えがあります。",
    "館内が清潔で快適でした。案内表示も分かりやすく迷いません。",
    "料金のわりに展示内容が少なく物足りない。混雑していて疲れました。",
]


def _mk(i: int, text: str) -> review_csv.ParsedReview:
    return review_csv.ParsedReview(
        review_id=f"r{i}", rating=(i % 5) + 1, text=text,
        review_date="2025-01-01T00:00:00Z", reviewer_name="u",
        local_guide=False, likes=None, owner_response="",
        owner_response_date="", subscores=[],
    )


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "t.db")
    db.init_db(c)
    for fi in range(6):
        fid = db.upsert_facility(c, f"施設{fi}")
        db.insert_reviews(c, fid, [
            _mk(fi * 10 + j, t) for j, t in enumerate(_TEXTS)
        ])
    c.commit()
    text_analysis._token_cache.clear()
    text_analysis._token_cache_new.clear()
    return c


# --------------------------------------------------------------------------- #
# 残りを数える
# --------------------------------------------------------------------------- #
def test_survey_lists_everything_before_the_first_run(conn):
    todo, total = warmup.survey(conn)
    assert total == 6
    assert [t.name for t in todo] == [f"施設{i}" for i in range(6)]
    assert all(t.n_reviews == len(_TEXTS) for t in todo)


def test_survey_reads_in_two_queries_regardless_of_facility_count(conn):
    """施設ごとに問い合わせない（Turso では 1クエリ = 1 HTTP 往復）。"""
    calls = []
    real = conn.execute
    proxy = type("P", (), {
        "execute": lambda _s, sql, *a: (calls.append(sql) or real(sql, *a)),
    })()
    warmup.survey(proxy)
    assert len(calls) == 2, f"施設一覧＋キャッシュの2クエリで済ませること（{len(calls)}）"


def test_survey_shrinks_as_batches_complete(conn):
    todo, _ = warmup.survey(conn)
    warmup.run_batch(conn, warmup.next_batch(todo, 2))

    todo2, total = warmup.survey(conn)
    assert total == 6
    assert len(todo2) == 4
    assert [t.name for t in todo2] == [f"施設{i}" for i in range(2, 6)]


# --------------------------------------------------------------------------- #
# 分割して最後まで進める
# --------------------------------------------------------------------------- #
def test_repeated_batches_finish_the_whole_set(conn):
    seen = []
    for _ in range(10):                      # 無限ループ防止の上限
        todo, _total = warmup.survey(conn)
        if not todo:
            break
        res = warmup.run_batch(conn, warmup.next_batch(todo, 2))
        seen += res.computed
        assert res.n_done > 0, "1件も進まないと自動継続が無限に回る"
    assert sorted(seen) == [f"施設{i}" for i in range(6)]
    assert warmup.survey(conn)[0] == []


def test_next_batch_never_returns_empty_for_a_nonempty_todo(conn):
    todo, _ = warmup.survey(conn)
    assert len(warmup.next_batch(todo, 0)) == 1      # 0を渡しても1件は進む
    assert len(warmup.next_batch(todo, 99)) == 6     # 残り以上は残り全部


def test_batch_result_matches_a_direct_analysis(conn):
    """分割して計算しても、まとめて計算した結果と一致すること。"""
    want = topic_score.analyze_facility(conn, "施設0")
    todo, _ = warmup.survey(conn)
    warmup.run_batch(conn, [t for t in todo if t.name == "施設0"])

    row = db.get_topic_score_cache_bulk(conn)[(todo[0].facility_id, len(_TEXTS))]
    assert row["overall_score"] == pytest.approx(want.overall_score)
    assert row["n_sentences"] == want.n_sentences


# --------------------------------------------------------------------------- #
# 途中で止まっても失わない
# --------------------------------------------------------------------------- #
def test_each_batch_persists_before_returning(conn):
    """バッチが返った時点で、DBに書けていること（最後にまとめて書かない）。"""
    todo, _ = warmup.survey(conn)
    res = warmup.run_batch(conn, warmup.next_batch(todo, 3))

    assert len(res.computed) == 3
    assert res.tokens_saved > 0, "形態素解析の結果がこのバッチで保存されていない"
    # 別の接続から見えること＝本当に書けている
    assert len(db.get_topic_score_cache_bulk(conn)) == 3
    assert conn.execute("SELECT COUNT(*) FROM token_cache").fetchone()[0] > 0


def test_a_broken_facility_does_not_take_down_the_batch(conn, monkeypatch):
    """1施設が転んでも残りは計算され、書き込まれること。"""
    todo, _ = warmup.survey(conn)
    batch = warmup.next_batch(todo, 3)          # 施設0 / 施設1 / 施設2

    real = topic_score.analyze_reviews
    seen = {"n": 0}

    def _boom(texts, *a, **k):
        seen["n"] += 1
        if seen["n"] == 2:                      # 2件目（施設1）だけ転ばせる
            raise RuntimeError("解析に失敗")
        return real(texts, *a, **k)

    monkeypatch.setattr(topic_score, "analyze_reviews", _boom)
    res = warmup.run_batch(conn, batch)

    assert res.computed == ["施設0", "施設2"], "転んだ次の施設で止まっている"
    assert [n for n, _why in res.failed] == ["施設1"]
    assert "解析に失敗" in res.failed[0][1]

    # 成功した2件は書けている／転んだ1件は未計算のまま残る＝次回また対象になる
    assert len(db.get_topic_score_cache_bulk(conn)) == 2
    assert [t.name for t in warmup.survey(conn)[0]] == [
        "施設1", "施設3", "施設4", "施設5",
    ]


def test_tokens_stay_pending_when_the_write_fails():
    """書き込みに失敗したら『書き出し待ち』から消さない。

    消してしまうと、次に呼んでも二度と書かれず、一番重い形態素解析の結果が
    永久に失われる。
    """
    text_analysis._token_cache_new.clear()
    text_analysis._token_cache_new["h1"] = ["あ", "い"]

    class _Broken:
        def execute(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

        def execute_pipeline(self, *_a, **_k):
            raise requests.exceptions.HTTPError("502")

        def commit(self):
            pass

    assert text_analysis.flush_token_cache(_Broken()) == 0
    assert text_analysis._token_cache_new == {"h1": ["あ", "い"]}, (
        "書けていないのに書き出し待ちから消している"
    )
    text_analysis._token_cache_new.clear()


def test_flush_clears_only_after_a_successful_write(conn):
    text_analysis._token_cache_new.clear()
    text_analysis._token_cache_new["h9"] = ["か", "き"]
    assert text_analysis.flush_token_cache(conn) == 1
    assert text_analysis._token_cache_new == {}
    assert text_analysis.flush_token_cache(conn) == 0    # 二重書きしない


def test_empty_batch_is_a_no_op(conn):
    res = warmup.run_batch(conn, [])
    assert res.n_done == 0 and res.tokens_saved == 0 and not res.failed


def test_facility_without_text_is_skipped_not_failed(tmp_path):
    """本文が無い施設は失敗ではなく skip（毎回リトライさせない）。"""
    c = db.get_conn(tmp_path / "e.db")
    db.init_db(c)
    fid = db.upsert_facility(c, "本文なし館")
    db.insert_reviews(c, fid, [
        review_csv.ParsedReview(
            review_id="x1", rating=5, text="",
            review_date="2025-01-01T00:00:00Z", reviewer_name="u",
            local_guide=False, likes=None, owner_response="",
            owner_response_date="", subscores=[],
        )
    ])
    c.commit()

    todo, total = warmup.survey(c)
    assert total == 1
    res = warmup.run_batch(c, todo)
    assert res.skipped == ["本文なし館"] and not res.failed


# --------------------------------------------------------------------------- #
# 「進んだ」の判定は、計算できたかではなく DB に書けたか
#
#   キャッシュの書き込みは失敗しても分析を止めない設計なので、
#   set_topic_score_cache_bulk は例外を飲んで 0 を返す。これを「成功」と
#   扱ってしまい、自動継続が同じ5施設を延々と計算し直した（386回まで確認）。
# --------------------------------------------------------------------------- #
class _WriteFails:
    """読めるが書けない接続。502 が続いている状態を模す。"""

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a):
        if " ".join(str(sql).split()).lower().startswith("insert"):
            raise requests.exceptions.HTTPError("502")
        return self._real.execute(sql, *a)

    def commit(self):
        self._real.commit()


def test_batch_reports_that_nothing_was_persisted(conn):
    res = warmup.run_batch(_WriteFails(conn), warmup.next_batch(
        warmup.survey(conn)[0], 3))

    assert res.computed, "計算自体はできているはず"
    assert res.scores_saved == 0
    assert not res.advanced, "書けていないのに『進んだ』と言っている"
    assert any("書き込めませんでした" in why for _n, why in res.failed), (
        "書けなかったことを握りつぶしている"
    )
    # 本当に1件も入っていないこと
    assert db.get_topic_score_cache_bulk(conn) == {}


def test_auto_continue_would_stop_when_nothing_is_persisted(conn):
    """advanced を見て打ち切れば、残りが減らないループに入らないこと。"""
    broken = _WriteFails(conn)
    rounds = 0
    while rounds < 50:
        todo, _ = warmup.survey(conn)
        if not todo:
            break
        rounds += 1
        if not warmup.run_batch(broken, warmup.next_batch(todo, 5)).advanced:
            break
    assert rounds == 1, f"残りが減らないのに {rounds} 回も回っている"


def test_advanced_is_true_on_a_normal_batch(conn):
    res = warmup.run_batch(conn, warmup.next_batch(warmup.survey(conn)[0], 2))
    assert res.scores_saved == 2 and res.advanced


def test_advanced_is_true_when_everything_was_skipped(tmp_path):
    """本文が無いだけの施設は書くものが無い。それでも残りは減るので進んだ扱い。"""
    c = db.get_conn(tmp_path / "s.db")
    db.init_db(c)
    fid = db.upsert_facility(c, "本文なし館")
    db.insert_reviews(c, fid, [
        review_csv.ParsedReview(
            review_id="x1", rating=5, text="",
            review_date="2025-01-01T00:00:00Z", reviewer_name="u",
            local_guide=False, likes=None, owner_response="",
            owner_response_date="", subscores=[],
        )
    ])
    c.commit()
    res = warmup.run_batch(c, warmup.survey(c)[0])
    assert res.skipped and res.scores_saved == 0 and res.advanced


def test_admin_page_gates_auto_continue_on_advanced():
    """画面側が n_done ではなく advanced で継続判定していること。"""
    from pathlib import Path

    from src.ui import admin_mode

    src = Path(admin_mode.__file__).read_text(encoding="utf-8")
    page = src[src.index('elif _page == "warmup":'):src.index('elif _page == "dummy":')]
    assert "_res.advanced" in page
    assert "_res.n_done > 0" not in page
