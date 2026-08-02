"""分析ワーカー(_analysis_worker)を Streamlit 無しでそのまま実行する統合テスト。

このテストが無かったせいで、受け渡し用 dict の名前が施設ループのローカル変数
`result`（TopicScoreResult）と衝突して
    TypeError: 'TopicScoreResult' object does not support item assignment
が本番でしか出なかった。ワーカーは render() のクロージャではなくモジュール関数
なので、ここから普通に呼べる。
"""
from __future__ import annotations

import threading

import pytest

from src import db, review_csv
from src.ui import analysis_mode


def _mk_review(i: int, rating: int, text: str) -> review_csv.ParsedReview:
    return review_csv.ParsedReview(
        review_id=f"r{i}", rating=rating, text=text,
        review_date=f"2025-0{(i % 9) + 1}-01T00:00:00Z", reviewer_name=f"u{i}",
        local_guide=False, likes=None, owner_response="", owner_response_date="",
        subscores=[],
    )


_TEXTS = [
    "スタッフの対応がとても丁寧で気持ちよく過ごせました。展示も見応えがあります。",
    "館内が清潔で快適でした。案内表示も分かりやすく迷いません。",
    "料金のわりに展示内容が少なく物足りない。混雑していて疲れました。",
    "子どもが体験コーナーを楽しんでいました。駐車場が広くて助かります。",
    "静かな空間でゆっくり鑑賞できました。カフェの飲み物も美味しかったです。",
    "アクセスが少し不便でした。バスの本数が少ないので車が無いと厳しいです。",
]


@pytest.fixture
def db_path(tmp_path):
    """3施設・各6件の口コミを持つテスト用DBを作る。"""
    path = tmp_path / "reviews.db"
    conn = db.get_conn(path)
    db.init_db(conn)
    for fi, name in enumerate(("対象館", "競合A", "競合B")):
        fid = db.upsert_facility(
            conn, name, ftype="target" if fi == 0 else "comparison", category="美術館"
        )
        db.insert_reviews(conn, fid, [
            _mk_review(fi * 100 + i, (i % 5) + 1, t) for i, t in enumerate(_TEXTS)
        ])
    conn.commit()
    return path


def _prog(db_path, target="対象館", peers=None) -> dict:
    conn = db.get_conn(db_path)
    fid = conn.execute("SELECT id FROM facility WHERE name = ?", (target,)).fetchone()["id"]
    rows = conn.execute(
        "SELECT rating, text FROM review WHERE facility_id = ?", (fid,)
    ).fetchall()
    revs = [(r["rating"], r["text"] or "") for r in rows]
    names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
    return {
        "step": 2, "detail": "", "running": True, "done": False, "error": None,
        "_target": target, "_an_mode": "compare", "_axis": "comparison_avg",
        "_specific_name": None, "_api_key": "",          # 空 → LLMを呼ばない
        "_revs": revs, "_n_rev": len(revs),
        "_n_with_text": sum(1 for _, t in revs if t.strip()),
        "_all_names": names, "_prof_key": f"_vb_profile_{target}",
        "_cached_profile": None, "_cached_matrix": None,
        "_matrix_ss_key": "_vb_matrix_test", "_peers_for_bundle": peers,
        "_db_path": db_path,
    }


def test_worker_runs_end_to_end(db_path):
    prog = _prog(db_path)
    analysis_mode._analysis_worker(prog)

    assert prog["error"] is None, prog["error"]
    assert prog["done"] is True
    assert prog["step"] == 6

    out = prog["result"]
    # メインスレッドが session_state へ流し込むキーが揃っていること
    for key in ("an_preview", "an_result_path", "an_topic_list", "an_topic_score",
                "analysis_target", "insights", "insights_facility", "an_axis",
                "an_specific_name", "an_peers_used"):
        assert key in out, f"missing {key}"

    assert out["analysis_target"] == "対象館"
    assert out["an_preview"]["target"] == "対象館"
    assert out["an_preview"]["n_reviews"] == len(_TEXTS)

    # プロファイルと感情スコア行列もセッションキャッシュとして返る
    assert out["_vb_profile_対象館"].facility_name == "対象館"
    assert set(out["_vb_matrix_test"]) == {"対象館", "競合A", "競合B"}

    # PPTX が実際に生成されている
    from pathlib import Path
    assert Path(out["an_result_path"]).exists()
    assert Path(out["an_result_path"]).stat().st_size > 0


def test_worker_result_is_a_plain_dict_not_a_score_object(db_path):
    """受け渡し用 dict が施設ループの result で潰されていないこと（回帰）。"""
    prog = _prog(db_path)
    analysis_mode._analysis_worker(prog)
    assert prog["error"] is None, prog["error"]
    assert isinstance(prog["result"], dict)


def test_worker_populates_db_caches_and_reuses_them(db_path):
    """1回目で topic_score_cache / text_profile_cache が埋まり、2回目で再利用される。"""
    conn = db.get_conn(db_path)
    assert conn.execute("SELECT COUNT(*) FROM topic_score_cache").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM text_profile_cache").fetchone()[0] == 0

    analysis_mode._analysis_worker(_prog(db_path))

    assert conn.execute("SELECT COUNT(*) FROM topic_score_cache").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM text_profile_cache").fetchone()[0] == 1

    # 2回目: 全施設がDBキャッシュから復元される
    prog2 = _prog(db_path)
    analysis_mode._analysis_worker(prog2)
    assert prog2["error"] is None, prog2["error"]
    matrix = prog2["result"]["_vb_matrix_test"]
    assert all(r.backend == "db_cache" for r in matrix.values()), \
        {n: r.backend for n, r in matrix.items()}

    # キャッシュ経由でもスコアは一致する（決定的であること）
    assert matrix["対象館"].sentiment_by_topic() == \
        prog2["result"]["an_topic_score"].sentiment_by_topic()


def test_worker_competitor_mode_restricts_bundle_scope(db_path):
    prog = _prog(db_path, peers=["競合A"])
    analysis_mode._analysis_worker(prog)
    assert prog["error"] is None, prog["error"]

    b = prog["result"]["an_preview"]
    assert b["comparison_scope"] == "competitor"
    assert b["total_fac"] == 2               # 対象館 + 競合A のみ（競合B は母数外）
    assert b["peer_names"] == ["競合A"]
    assert prog["result"]["an_peers_used"] == ["競合A"]


def test_worker_handles_unknown_facility_gracefully(db_path):
    """DBに無い施設名でも落ちない（空プロファイル・空スコアで完走する）。"""
    prog = _prog(db_path)
    prog["_target"] = "存在しない施設"
    analysis_mode._analysis_worker(prog)

    assert prog["error"] is None, prog["error"]
    assert prog["done"] is True
    assert prog["result"]["an_preview"]["n_reviews"] == 0


def test_worker_reports_error_instead_of_raising(db_path):
    """例外はスレッドを殺さず prog["error"] に入る（メインスレッドが表示する）。"""
    prog = _prog(db_path)
    del prog["_all_names"]          # 必須キー欠落 → KeyError
    analysis_mode._analysis_worker(prog)

    assert prog["done"] is False
    assert prog["error"] and "Traceback" in prog["error"]
    assert "_all_names" in prog["error"]


def test_worker_survives_being_run_in_a_bare_thread(db_path):
    """実運用と同じ、ScriptRunContext を持たない素のスレッドで完走すること。"""
    prog = _prog(db_path)
    t = threading.Thread(target=analysis_mode._analysis_worker, args=(prog,), daemon=True)
    t.start()
    t.join(timeout=180)

    assert not t.is_alive(), "worker thread hung"
    assert prog["error"] is None, prog["error"]
    assert prog["done"] is True
    assert isinstance(prog["result"], dict)
