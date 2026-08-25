"""Analysis-mode screens (setup / running / preview) for VoiceBAUM.

Extracted from app.py. render() is called once per Streamlit rerun when
app_mode == "analysis".
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
import traceback
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src import (
    analysis, auth, charts, config, csv_profiler, db, geocode, images, kaizode,
    llm, places, preview, report, review_csv, score_excel, scoring, search,
    discussion, slides, text_analysis, timeline, topic_score, topics, voices,
)
from src.ui import components, data
from src.ui.theme import ACCENT, ACCENT_RING, ACCENT_SOFT


def _resolve_kaizode_key() -> str:
    key = os.environ.get("KAIZODE_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("KAIZODE_API_KEY", "") or ""
        except Exception:
            key = ""
    return key or ""


def _status_to_progress(status: int) -> tuple[int, str]:
    """KAIZODE status → (進捗率%, ステータスラベル)"""
    labels = {
        10: "レビュー抽出中",
        20: "解析実行中",
        30: "完了",
        40: "失敗",
    }
    progress_map = {10: 33, 20: 66, 30: 100, 40: 0}
    return progress_map.get(status, 0), labels.get(status, "不明")


def _kz_order(conn, key: str, url: str, name: str) -> str:
    """KAIZODEに1施設の収集を発注する。dataset_id を返す。"""
    try:
        client = kaizode.KaizodeClient(api_key=key)
        ds = client.create_dataset(
            name, [{"url": url, "review_target_name": name}])
        return ds.get("dataset_id") or ""
    except kaizode.KaizodeError as _e:
        st.error(str(_e))
        return ""


def _kz_pull(conn, key: str, query: str) -> bool:
    """完了分をKAIZODEから取り込み、対象施設が入れば分析対象にセット。成功時 True。"""
    try:
        client = kaizode.KaizodeClient(api_key=key)
        with st.spinner("KAIZODEから完了分を取り込み中…"):
            res = kaizode.sync_datasets(client, conn, log=lambda *_a: None)
        data.topic_matrix_cached.clear()
        data.clear_list_caches()
        _stats = db.facility_stats(conn, query)
        if _stats and _stats["n_reviews"] > 0:
            st.success(f"✅ 「{query}」の口コミを取り込みました。分析できます。")
            st.session_state["an_target"] = query
            st.rerun()
            return True
        else:
            st.info(
                f"取り込みを実行しました（新規 {res['inserted']:,} 件）が、"
                f"「{query}」の口コミはまだありません（収集が未完了、または名前が不一致の可能性）。"
            )
        if res.get("limit_reached"):
            st.warning("今月の取得上限に達したため途中で停止しました。")
    except kaizode.KaizodeError as _e:
        st.error(str(_e))
    return False


@st.fragment(run_every="3s")
def _kz_progress_tracker(conn, key: str, dataset_id: str, facility_name: str, query: str) -> None:
    """進捗トラッキング（fragment）。3秒ごとにこの部分だけを自動更新する。

    st.fragment のおかげでページ全体は再実行されないため、sleep+rerun のような
    もたつき・ちらつきが起きない（更新されるのはこのカードの中身だけ）。
    """
    try:
        client = kaizode.KaizodeClient(api_key=key)
        ds = client.get_dataset(dataset_id)
    except kaizode.KaizodeError:
        st.error("データセットの状態が取得できません。")
        return

    status = ds.get("status", 0)
    progress, status_label = _status_to_progress(status)

    # ── プログレスバー表示 ─────────────────────── #
    with st.container(border=True):
        st.markdown(f"🔄 **「{facility_name}」の口コミを集めています**")
        st.progress(progress / 100, text=f"{progress}%")
        st.caption(f"⏳ {status_label}")

    # ── 完了チェック ─────────────────────────── #
    if status == kaizode.STATUS_DONE:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        # 完了時は分析画面へ切り替えるため、ここだけはページ全体を rerun する
        if _kz_pull(conn, key, query):
            return
        if st.button("⬇️ 取り込みを再度試す", key="an_kz_retry_import", width="stretch"):
            _kz_pull(conn, key, query)
        return

    if status == 40:
        st.error("❌ 収集に失敗しました。別の施設名を試すか、管理者に連絡してください。")
        return

    # ── 手動更新 ────────────────────────────────────────────── #
    # scope="fragment" は「fragment の自動rerun中」でないと呼べない制約があり、
    # 初回描画直後にクリックされると例外になるため、素直に通常rerunにする
    # （自動更新（3秒毎）は run_every 側が fragment scope で滑らかに処理する）。
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    if st.button("🔄 今すぐ確認", key="an_kz_check_now", width="stretch"):
        st.rerun()




def _kz_collect_section(conn, query: str) -> None:
    """KAIZODE 収集フロー（シンプル UI）。

    STEP 1: URL/施設名入力 → STEP 2: 進捗中 → STEP 3: 自動インポート

    発注・取り込みは **ログイン（管理者）必須**（KAIZODEの費用/枠を消費するため）。
    """
    query = (query or "").strip()
    if not query:
        return
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    if not st.session_state.get("admin_authed"):
        st.info(f"「{query}」の口コミはまだありません。収集するにはログイン（管理者）が必要です。")
        if st.button("🔐 ログインして収集する", key="an_kz_login", width="stretch"):
            st.session_state["app_mode"] = "admin"
            st.rerun()
        return

    key = _resolve_kaizode_key()
    if not key:
        st.warning("KAIZODE APIキーが未設定です（管理 → 📡 KAIZODE連携 で設定してください）。")
        return

    _rem = kaizode.monthly_remaining(conn)
    st.caption(f"今月のKAIZODE残枠: {_rem:,} / {kaizode.MONTHLY_LIMIT:,} 件")

    # ── 進行中の収集があれば、そちらを優先表示 ────────────────── #
    _ongoing_key = f"an_kz_ongoing::{query}"
    _ongoing = st.session_state.get(_ongoing_key)
    if _ongoing:
        _kz_progress_tracker(conn, key, _ongoing["dataset_id"], _ongoing["facility_name"], query)
        return

    # ── KAIZODE側にこの施設の収集が既にあるか ──────────────────── #
    _mkey = f"an_kz_match::{query}"
    if _mkey not in st.session_state:
        try:
            client = kaizode.KaizodeClient(api_key=key)
            st.session_state[_mkey] = kaizode.match_datasets(
                client.list_datasets(), query)
        except kaizode.KaizodeError:
            st.session_state[_mkey] = []
    _matches = st.session_state.get(_mkey) or []
    if _matches:
        st.markdown("**既存の収集:**")
        for _m in _matches:
            _lbl = _m.get("status_label", "")
            _done = _m.get("status") == kaizode.STATUS_DONE
            _icon = "✅" if _done else "⏳"
            st.caption(f"{_icon} 「{_m.get('dataset_name')}」— {_lbl}")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── STEP 1: URL/施設名入力 ────────────────────────────────── #
    _ikey = f"an_kz_input::{query}"
    _inp = st.text_input(
        "Google MapsのURL または 施設名を入力",
        key="an_kz_url_input",
        placeholder="例: https://www.google.com/maps/search/... または 施設名",
    )
    if not _inp:
        return

    # ── 自動抽出 + プレビュー ──────────────────────────────────── #
    _parsed_name = geocode.parse_maps_url(_inp)
    _facility_name = (_parsed_name or _inp).strip()
    _typed_url = bool(_parsed_name)          # URL を貼られたか、名前を打たれたか

    # 名前を打たれたときは Google Places で施設を1件に確定させ、
    # place_id を指す Maps URL を自動で作る。
    #   検索URL（/maps/search/?query=名前）だと同名の別施設を拾いうる。
    #   KAIZODE は1発注ぶんの収集枠を消費するので、狙った施設を指したい。
    _resolved = None
    if not _typed_url:
        _gkey = places.get_api_key()
        _rkey = f"an_kz_place::{_facility_name}"
        if _gkey and _rkey not in st.session_state:
            with st.spinner("Google マップで施設を検索中…"):
                _r = places.resolve(_facility_name, _gkey)
            st.session_state[_rkey] = (
                {"place_id": _r.place_id, "name": _r.name,
                 "address": _r.address, "url": _r.maps_url} if _r else {}
            )
        _resolved = st.session_state.get(_rkey) or None

    # 住所は Places が引けていればそれ、無ければ OpenStreetMap
    if _resolved and _resolved.get("address"):
        _addr = _resolved["address"][:60]
    else:
        _pkey = f"an_kz_preview::{_facility_name}"
        if _pkey not in st.session_state:
            with st.spinner("施設情報を取得中…"):
                _profile = geocode.lookup(_facility_name)
            st.session_state[_pkey] = _profile or {}
        _profile = st.session_state.get(_pkey) or {}
        _addr = (_profile.get("address") or "")[:60] if _profile else "(情報なし)"

    # 発注に使う URL を決める（貼られた URL > place_id > 名前で検索）
    if _typed_url:
        _maps_url = _inp
    elif _resolved and _resolved.get("url"):
        _maps_url = _resolved["url"]
    else:
        _maps_url = kaizode.maps_search_url(_facility_name)

    st.caption(f"🏢 {_resolved['name'] if _resolved and _resolved.get('name') else _facility_name}"
               f"  ·  {_addr}")
    if _resolved and _resolved.get("url"):
        st.success("✅ Google マップで施設を特定しました（この1件に対して発注します）")
    elif not _typed_url and not places.get_api_key():
        st.info(
            "GOOGLE_MAPS_API_KEY が未設定のため、施設名での検索URLを使います。"
            "同名の別施設を拾う可能性があるので、Google マップの URL を"
            "貼るほうが確実です。"
        )
    elif not _typed_url:
        st.warning(
            "Google マップで施設を特定できませんでした。名前での検索URLを使います。"
            "確実にするには Google マップの URL を貼ってください。"
        )
    st.text_input("KAIZODE に渡す Google マップ URL", value=_maps_url,
                  key="an_kz_resolved_url", disabled=True)

    if st.button("📡 今すぐ集める", key="an_kz_order", type="primary",
                 width="stretch"):
        _dsid = _kz_order(conn, key, _maps_url, _facility_name)
        if _dsid:
            # 確定した place_id は覚えておく（保存が許されている唯一のもの）
            if _resolved and _resolved.get("place_id"):
                db.set_place_id(conn, _facility_name, _resolved["place_id"])
            st.session_state[_ongoing_key] = {
                "dataset_id": _dsid,
                "facility_name": _facility_name,
            }
            st.rerun()


# ── Background thread: steps ③–⑥ ─────────────────────────────────────────── #
#  重要: このスレッドから st.session_state に書いてはいけない。
#  ScriptRunContext がスレッド属性として持ち回られる仕組みのため、素の Thread
#  では ctx が None になり、Streamlit は書き込みを捨てられるグローバルのモック
#  SessionState に黙って流す（エラーも警告も出ない）。
#  → 成果物は素の dict である prog["result"] に貯め、session_state への反映は
#    メインスレッド（render() のランニング画面の分岐 ①）が行う。
#
#  render() のクロージャではなくモジュール関数にしてあるのは、Streamlit 無しで
#  そのままテストから実行できるようにするため（クロージャのままだと、ここでの
#  取り違えを一切テストで検出できなかった）。
def _mark(prog: dict, phase: str | None) -> None:
    """いま何をしているかと、その開始時刻をワーカー側で記録する。

    ローディングカードの経過秒は CSS アニメーションなので、サーバが止まって
    いてもブラウザ側で数字だけ増え続ける（＝止まっているのに動いて見える）。
    ここで打つ時刻を使って、メインスレッドが「サーバから見た経過秒」を出す。
    どの工程で待たされているのかを、環境に入らなくても切り分けられるようにする。
    """
    now = time.time()
    prev = prog.get("phase")
    started = prog.get("phase_started")
    if prev and started:
        prog.setdefault("timings", []).append((prev, round(now - started, 1)))
    prog["phase"] = phase
    prog["phase_started"] = now


@st.cache_data(ttl=1800, show_spinner=False)
def _places_cached(_conn_key: str, name: str, api_key: str) -> dict:
    """Places の写真URLと住所をセッション内で一時的に持つ。

    Streamlit は操作のたびにスクリプト全体を再実行するので、素で呼ぶと
    ボタンひとつで6施設ぶんの API 呼び出しが飛ぶ。写真の実体は保持せず、
    URL と住所だけを短時間（30分）持つ性能目的の一時キャッシュ。

    住所は写真と同じ Details 呼び出しに相乗りさせている（photos を要求した
    時点で Pro 階層なので、住所を足しても課金は変わらない）。
    """
    from src import places  # noqa: PLC0415

    conn = db.get_conn(config.DB_PATH)
    d = places.details_for_facility(conn, name, api_key)
    return {
        "url": d.photo.url if d.photo else "",
        "attribution": d.photo.attribution if d.photo else "",
        "address": d.address,
    }


def _places_photos(conn, bundle: dict) -> None:
    """写真の空き枠を Google Places で埋める（画面プレビュー専用）。

    規約上、写真は保存できない（無期限保存が許されているのは place_id だけ）。
    DB に焼かず、Google の URL を <img src> で参照する。よって PPTX には入らない。
    手動アップロード済みの枠は上書きしない（そちらは配布物にも使えるため）。
    """
    from src import places  # noqa: PLC0415

    key = places.get_api_key()
    if not key or not st.session_state.get("use_places_photos", True):
        return

    attrs: list[str] = []
    ck = str(config.DB_PATH)

    got = _places_cached(ck, bundle.get("target", ""), key)
    if not bundle.get("photo_data_uri") and got.get("url"):
        bundle["photo_data_uri"] = got["url"]
        attrs.append(got["attribution"])
    # 住所は OpenStreetMap が引けなかったときの穴埋め（日本の施設は
    # Nominatim の網羅性が低く「—」のままになりがち）。手入力があれば触らない。
    if got.get("address") and not (bundle.get("address") or "").strip():
        bundle["address"] = got["address"]
        bundle["address_from_google"] = True

    for peer in (bundle.get("peer_display") or []):
        if peer.get("photo_data_uri"):
            continue
        pg = _places_cached(ck, peer.get("name", ""), key)
        if pg.get("url"):
            peer["photo_data_uri"] = pg["url"]
            attrs.append(pg["attribution"])

    if attrs:
        # 帰属表示は必須。重複を潰して並び順は保つ。
        bundle["photo_attribution"] = "写真: " + "、".join(dict.fromkeys(attrs))


def _analysis_worker(prog: dict) -> None:
    try:
        # 施設ループのローカル変数 result と衝突しない名前にすること。
        ss_out: dict = {}       # ← session_state に入れてほしいもの
        db.reset_retry_budget()  # この分析でリトライに使ってよい時間を戻す
        tconn = db.get_conn(prog.get("_db_path"))  # fresh thread-local connection
        tgt   = prog["_target"]
        amode = prog["_an_mode"]
        ax    = prog["_axis"]
        spn   = prog["_specific_name"]
        akey  = prog["_api_key"]
        revs  = prog["_revs"]
        n_wt  = prog["_n_with_text"]
        all_names = prog["_all_names"]
        pkey  = prog["_prof_key"]

        # ③-a  テキストプロファイル（session_state → DBキャッシュ → build_profile）
        _mark(prog, "テキストプロファイル")
        prog["step"] = 2
        _profile = prog["_cached_profile"]
        if not _profile:
            _tgt_fid_row = tconn.execute(
                "SELECT id FROM facility WHERE name = ?", (tgt,)
            ).fetchone()
            _tgt_fid = _tgt_fid_row["id"] if _tgt_fid_row else None
            _tp_cached = (
                db.get_text_profile_cache(tconn, _tgt_fid, n_wt)
                if _tgt_fid else None
            )
            if _tp_cached:
                prog["detail"] = f"「{tgt}」のキーワードプロファイル — DBキャッシュから読み込み中"
                _tfidf_recs = json.loads(_tp_cached["tfidf_json"])
                _bi_recs    = json.loads(_tp_cached["bigrams_json"])
                _tri_recs   = json.loads(_tp_cached["trigrams_json"])
                _profile = text_analysis.TextProfile(
                    facility_name=tgt,
                    n_reviews=n_wt,
                    tfidf_keywords=(
                        pd.DataFrame(_tfidf_recs) if _tfidf_recs
                        else pd.DataFrame(columns=["単語", "スコア"])
                    ),
                    bigrams=(
                        pd.DataFrame(_bi_recs) if _bi_recs
                        else pd.DataFrame(columns=["フレーズ", "件数"])
                    ),
                    trigrams=(
                        pd.DataFrame(_tri_recs) if _tri_recs
                        else pd.DataFrame(columns=["フレーズ", "件数"])
                    ),
                    high_rated=json.loads(_tp_cached["high_rated_json"]),
                    low_rated=json.loads(_tp_cached["low_rated_json"]),
                    empty=len(_tfidf_recs) == 0,
                )
            else:
                prog["detail"] = f"「{tgt}」の本文 {n_wt:,} 件からキーワードを抽出中"
                _profile = text_analysis.build_profile(tconn, tgt, top_n=20)
                if _tgt_fid and not _profile.empty:
                    try:
                        db.set_text_profile_cache(
                            tconn, _tgt_fid, n_wt,
                            json.dumps(_profile.tfidf_keywords.to_dict("records")),
                            json.dumps(_profile.bigrams.to_dict("records")),
                            json.dumps(_profile.trigrams.to_dict("records")),
                            json.dumps(_profile.high_rated),
                            json.dumps(_profile.low_rated),
                        )
                    except Exception:
                        pass
        ss_out[pkey] = _profile

        # ③-b  全施設の感情スコア行列
        #   優先順: session_state / @st.cache_data → DBキャッシュ → 計算
        prebuilt = prog.get("_cached_matrix")
        total_fac = len(all_names)
        if prebuilt:
            matrix = prebuilt
            prog["detail"] = f"感情スコア {total_fac} 施設 — セッションキャッシュから読み込み完了"
        else:
            # facility_id と n_reviews をまとめて取得（1クエリ）
            fac_rows = tconn.execute(
                "SELECT f.id, f.name, COUNT(r.id) as nr "
                "FROM facility f LEFT JOIN review r ON r.facility_id = f.id "
                "GROUP BY f.id"
            ).fetchall()
            fac_info = {row["name"]: (row["id"], row["nr"]) for row in fac_rows}

            # キャッシュは施設ごとに引かず1クエリでまとめて読む。
            # Turso は 1クエリ = 1 HTTPリクエストなので、施設数ぶん往復すると
            # 遅いうえに、その回数だけ 502 を踏む機会が増える。
            cache_all = db.get_topic_score_cache_bulk(tconn)

            # 本文も同じ理由でまとめて読む。キャッシュに無い施設だけを引く。
            _todo = [
                n for n in all_names
                if fac_info.get(n) and tuple(fac_info[n]) not in cache_all
            ]
            if _todo:
                prog["detail"] = f"未計算 {len(_todo)} 施設の口コミ本文をまとめて読み込み中"
            texts_by_fac = db.review_texts_by_facility(tconn, _todo)

            matrix = {}
            pending_cache: list[tuple] = []
            n_cached, n_computed = 0, 0
            for i, fname in enumerate(all_names):
                if prog.get("cancelled"):
                    return          # 別の分析が始まったので、ここで手を引く
                fid_n = fac_info.get(fname)
                cached_row = cache_all.get(tuple(fid_n)) if fid_n else None
                if cached_row:
                    topics_data = json.loads(cached_row["topics_json"])
                    ts_topics = [
                        topic_score.TopicScore(**t) for t in topics_data
                    ]
                    matrix[fname] = topic_score.TopicScoreResult(
                        topics=ts_topics,
                        overall_score=cached_row["overall_score"],
                        n_reviews=fid_n[1],
                        n_sentences=cached_row["n_sentences"],
                        backend="db_cache",
                        empty=len(ts_topics) == 0,
                    )
                    n_cached += 1
                    prog["detail"] = (
                        f"感情スコア {i + 1}/{total_fac} 施設"
                        f" — DBキャッシュ {n_cached} 件・計算済み {n_computed} 件"
                    )
                else:
                    prog["detail"] = f"感情スコア {i + 1}/{total_fac} 施設: {fname}"
                    # 本文は上でまとめて読んである（施設ごとに引き直さない）
                    _txts = texts_by_fac.get(fname)
                    result = (
                        topic_score.analyze_reviews(_txts) if _txts is not None
                        else topic_score.analyze_facility(tconn, fname)
                    )
                    matrix[fname] = result
                    n_computed += 1
                    # DBに保存（次回 Streamlit 再起動後も有効）。
                    # 1件ずつ書くと施設数ぶん往復するので溜めてまとめて書く。
                    # 途中で中断されても、失うのは書けなかったぶんの再計算だけ。
                    if fid_n and not result.empty:
                        topics_json_str = json.dumps([
                            {"name": t.name, "weight": t.weight,
                             "avg_score": t.avg_score, "total_score": t.total_score,
                             "salience": t.salience, "sentiment": t.sentiment}
                            for t in result.topics
                        ])
                        pending_cache.append((
                            fid_n[0], fid_n[1], topics_json_str,
                            result.overall_score, result.n_sentences,
                        ))
                        if len(pending_cache) >= 20:
                            db.set_topic_score_cache_bulk(tconn, pending_cache)
                            pending_cache = []

            db.set_topic_score_cache_bulk(tconn, pending_cache)

            # session_state にも書き戻す（同セッション内の再実行を高速化）
            ss_out[prog["_matrix_ss_key"]] = matrix

        _ts_result = matrix.get(tgt) or topic_score.analyze_facility(tconn, tgt)

        if prog.get("cancelled"):
            return

        # ④  TF-IDF トピック抽出
        _mark(prog, "TF-IDF")
        prog["step"]   = 3
        n_sent = _ts_result.n_sentences
        prog["detail"] = f"本文 {n_wt:,} 件・{n_sent:,} 文から特徴キーワードをTF-IDFで抽出中"
        _topic_list = topics.extract_topics(revs, n_topics=5)

        # ⑤  競合比較 ＋ LLMインサイト
        #    指定競合モードでは選択した施設だけを比較軸にする（DBの
        #    type='comparison' タグや全施設平均にすり替わらないように）。
        _sel_peers = prog.get("_peers_for_bundle")
        n_peers = len(_sel_peers) if _sel_peers else total_fac - 1
        _mark(prog, "競合比較・LLM")
        prog["step"]   = 4
        prog["detail"] = f"比較対象 {n_peers} 施設との 22 観点スコア差分を計算中"
        _insights = None
        if akey and not _profile.empty:
            _comp2 = analysis.build_comparison(
                tconn, tgt, ax, specific_name=spn, peers=_sel_peers
            )
            if _comp2 is None and not _sel_peers:
                _comp2 = analysis.build_comparison(tconn, tgt, "all_avg")
            _diff = _comp2.diff if _comp2 else None
            _kw = _profile.tfidf_keywords["単語"].tolist()
            _bi = (
                _profile.bigrams["フレーズ"].tolist()
                if not _profile.bigrams.empty else []
            )
            prog["detail"] = f"LLMに強み・弱み・示唆の生成を依頼中（キーワード {len(_kw)} 語）"
            _prompt = llm.build_prompt(
                tgt, _diff, _kw, _bi, _profile.high_rated, _profile.low_rated
            )
            _res = llm.generate_insights(_prompt, akey)
            if not _res.error:
                _insights = _res

        # ⑤-b  SLIDE 4 の変化点に「何が起きたか」を書かせる。
        #      影響ptは timeline 側で算出済みで、LLM には文章だけを任せる。
        #      失敗しても timeline.fallback_description に落ちるので致命ではない。
        _tgt_fid_row = tconn.execute(
            "SELECT id FROM facility WHERE name = ?", (tgt,)
        ).fetchone()
        _cps = []          # build_bundle が後で detect し直すので、ここでは説明だけ作る
        if akey and _tgt_fid_row:
            _series = db.monthly_sentiment_series(tconn, _tgt_fid_row["id"])
            _cps = timeline.detect_change_points(_series)
            if _cps:
                prog["detail"] = f"評価が動いた {len(_cps)} 時点の要因を口コミから抽出中"
                for _cp in _cps:
                    _cp._reviews = timeline.reviews_for_point(
                        tconn, _tgt_fid_row["id"], _cp.ym
                    )
                llm.explain_change_points(tgt, _cps, akey)   # 失敗時は空のまま

        # ⑤-c  SLIDE 6 の4象限に載せる代表口コミを選ばせる。
        #      引用は逐語でなければならないので、返ってきた抜粋が実在するかを
        #      voices.apply_llm_result 側で必ず検証する。
        _voices = None
        if akey and revs:
            prog["detail"] = "特徴的な口コミを4つの観点で抽出中"
            _vdata, _verr = llm.pick_voice_quadrants(tgt, revs, akey)
            if not _verr:
                _voices = voices.apply_llm_result(revs, _vdata)   # 不正なら None

        # ⑤-d  SLIDE 7 の企画仮説・打ち手。課題とスコアはコード側で確定済みで、
        #      LLM には文章と「実現しやすさ」の見立てだけを書かせる。
        def _disc(_iss):
            """build_bundle が課題を確定した時点で呼ばれる。失敗時は None。"""
            prog["detail"] = f"抽出した {len(_iss)} 課題の企画仮説を作成中"
            _ddata, _derr = llm.build_discussion_points(
                tgt, _iss, akey, samples=revs[:20]
            )
            return None if _derr else _ddata

        # ⑥  レポート生成
        #    ここは以前ひとかたまりで、詳細テキストが変わらないまま数分黙る
        #    ことがあった（どこで待っているのか外から分からない）。
        #    PPTX / スライド / 書き戻し の3つに割って、それぞれ経過を出す。
        prog["step"]   = 5
        _mark(prog, "スライド生成")
        prog["detail"] = f"「{tgt}」の分析レポート（PowerPoint）を生成中"
        _tmp = Path(tempfile.mkdtemp()) / f"VoiceBAUM_{tgt}.pptx"
        report.build_report(
            tconn, tgt,
            axis=ax if amode == "compare" else "comparison_avg",
            specific_name=spn,
            insights=_insights,
            topic_list=_topic_list if _topic_list else None,
            topic_score_result=_ts_result if not _ts_result.empty else None,
            profile=_profile,          # ②で計算済み。ここで作り直さない
            peers=_sel_peers,
            output_path=_tmp,
        )

        # ビルドバンドル（プレビュー用）
        #    ⑤-b〜⑤-d で LLM に書かせた変化点・代表口コミ・企画仮説を
        #    ここで渡す。渡し忘れると LLM を呼んだ結果が捨てられ、
        #    スライドは黙って fallback の文章になる。
        _mark(prog, "スライド組み立て")
        prog["detail"] = "分析スライドを組み立て中"
        _bundle = preview.build_bundle(
            tconn, tgt, matrix, _profile, _insights,
            peers_override=prog.get("_peers_for_bundle"),
            change_points=_cps or None,
            voices_result=_voices,
            discussion_result=_disc if akey else None,
        )

        # 結果を受け渡し用 dict へ（session_state 反映はメインスレッド）
        ss_out["an_preview"]        = _bundle
        ss_out["an_result_path"]    = str(_tmp)
        ss_out["an_topic_list"]     = _topic_list
        ss_out["an_topic_score"]    = _ts_result
        ss_out["analysis_target"]   = tgt
        ss_out["insights"]          = _insights
        ss_out["insights_facility"] = tgt
        ss_out["an_axis"]           = ax if amode == "compare" else "comparison_avg"
        ss_out["an_specific_name"]  = spn
        ss_out["an_peers_used"]     = _sel_peers   # PPTX再生成でも同じ比較軸を使う

        # 新しく解析したぶんを書き戻す（次回以降このぶんは計算不要になる）
        _mark(prog, "語彙キャッシュ書き戻し")
        prog["detail"] = "解析した語彙をDBに書き戻し中"
        try:
            text_analysis.flush_token_cache(tconn)
        except Exception:
            pass

        _mark(prog, None)
        prog["step"]   = 6
        prog["detail"] = "完了しました"
        prog["result"] = ss_out
        prog["done"]   = True   # ← result を入れてから最後に立てる

    except Exception:
        prog["error"] = traceback.format_exc()
        # 途中まででも解析済みの語彙は残す（次回の助けになる）
        try:
            text_analysis.flush_token_cache(db.get_conn(prog.get("_db_path")))
        except Exception:
            pass


def render():
    conn = data.get_conn()
    _all_facility_names = data.all_facility_names
    _facility_card = components.facility_card
    _loading_card_html = components.loading_card_html
    _review_counts = data.review_counts
    _facility_meta = data.facility_meta
    _selected_card_html = components.selected_card_html
    _topic_sig = data.topic_sig
    _photo_from_db = data.photo_from_db
    _infer_facilities_cached = data.infer_facilities_cached
    _parse_reviews_cached = data.parse_reviews_cached

    _names = _all_facility_names()

    # ── No data yet ──────────────────────────────────────────────────────── #
    if not _names:
        st.markdown('<div class="vb-step">STEP 0 — はじめに</div>', unsafe_allow_html=True)
        st.markdown('<h1 class="vb-h1">データを登録しましょう</h1>', unsafe_allow_html=True)
        st.markdown(
            '<p class="vb-sub">口コミデータがまだありません。'
            "右上の「⚙️ 管理」→「📥 データ取り込み」からCSVを投入してください。</p>",
            unsafe_allow_html=True,
        )
        st.info(
            "**手順**: 画面左上の 「⚙️ 管理」→「📥 データ取り込み」→ CSVをアップロード → 施設を選んで保存"
        )
        st.stop()

    # ══════════════════════════════════════════════════════════════════════ #
    # SETUP SCREEN
    # ══════════════════════════════════════════════════════════════════════ #
    if st.session_state["an_screen"] == "setup":
        # Hero search field: magenta magnifier + suggestion rows styled from buttons.
        #
        # 見た目は <input> ではなく **BaseWeb のラッパ**に持たせる。
        # input を直接 height:60px にすると、Streamlit 側の器は既定の高さ
        # （約40px）のままなので、はみ出したぶんが次の要素に隠れて
        # 検索窓の下端が切れる（実際に切れていた）。
        st.markdown("""
        <style>
        /* 器の高さを枠に合わせて確保する（これが無いと下端が隠れる） */
        div[data-testid="stTextInput"]{ min-height:64px!important; }
        /* 枠・影・虫めがねはラッパ側に */
        div[data-testid="stTextInput"] div[data-baseweb="input"]{
          height:60px!important;border-radius:15px!important;
          border:1.5px solid #E4E3DD!important;background-color:#fff!important;
          box-shadow:0 1px 2px rgba(20,30,40,.04),0 12px 30px rgba(20,30,40,.05)!important;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='%23B0338A' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='M21 21l-4.3-4.3'/%3E%3C/svg%3E")!important;
          background-repeat:no-repeat!important;background-position:18px center!important;
          background-size:22px 22px!important;overflow:visible!important;
        }
        div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within{
          border-color:#B0338A!important;
          box-shadow:0 0 0 4px rgba(176,51,138,.18)!important;
        }
        /* 内側の base-input は白で塗りつぶして角丸と虫めがねを覆うので透過させる */
        div[data-testid="stTextInput"] div[data-baseweb="base-input"]{
          background:transparent!important;background-color:transparent!important;
        }
        /* 中の input は素通し。枠を二重に描かない */
        div[data-testid="stTextInput"] input{
          height:100%!important;font-size:18px!important;padding-left:52px!important;
          background:transparent!important;border:none!important;
          box-shadow:none!important;color:#16202B!important;
        }
        [class*="st-key-an_sug_"] button{
          text-align:left!important;justify-content:flex-start!important;
          border:1px solid #EEEDE7!important;border-radius:12px!important;
          padding:12px 16px!important;font-weight:600!important;color:#16202B!important;
          background:#fff!important;box-shadow:0 1px 2px rgba(20,30,40,.03)!important;min-height:56px;}
        [class*="st-key-an_sug_"] button:hover{background:#F7F3F6!important;border-color:#B0338A!important;}
        </style>
        """, unsafe_allow_html=True)

        _meta = _facility_meta()
        _sp, _mid, _sp2 = st.columns([1, 2.4, 1])
        with _mid:
            st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
            st.markdown('<div class="vb-hero-title">VoiceBAUM</div>', unsafe_allow_html=True)
            st.markdown(
                '<p class="vb-hero-sub">オープン後の来場者評価（口コミ）を活用した実態分析ツール</p>',
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:30px'></div>", unsafe_allow_html=True)

            _target = st.session_state.get("an_target")

            if not _target:
                # ── 空の状態：検索 + 候補（ネイティブボタン）＋無効ボタン ─── #
                _q = st.text_input(
                    "施設名を入力", placeholder="施設名を入力",
                    key="an_search", label_visibility="collapsed",
                )
                _qs = _q.strip()
                if _qs:
                    _subs = [n for n in _names if _qs.lower() in n.lower()]
                    _hints = search.suggest(_qs, _names)
                    _seen, _cands = set(), []
                    for _n in _subs + _hints:
                        if _n not in _seen:
                            _seen.add(_n)
                            _cands.append(_n)
                    _cands = _cands[:8]
                    if _cands:
                        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
                        for _n in _cands:
                            _sub = _meta.get(_n, "")
                            if st.button(
                                f"{_n}　·　{_sub}", key=f"an_sug_{_n}",
                                width="stretch",
                            ):
                                st.session_state["an_target"] = _n
                                st.rerun()
                    # 完全一致がDBに無ければ、候補があってもKAIZODE収集の導線を出す
                    if not any(_qs == _n for _n in _names):
                        if _cands:
                            with st.expander("🔍 候補に無い？ KAIZODEで新しく収集する",
                                             expanded=False):
                                _kz_collect_section(conn, _qs)
                        else:
                            _kz_collect_section(conn, _qs)

                st.markdown(
                    '<div style="max-width:440px;margin:24px auto 0;text-align:center;'
                    'background:#E4E3DD;color:#A7ABB0;font-weight:700;font-size:15px;'
                    'padding:16px;border-radius:12px;">この内容で分析する</div>',
                    unsafe_allow_html=True,
                )

            else:
                # ── 選択済み：施設カード + 分析タイプ選択 + 実行ボタン ── #
                _chk = db.facility_stats(conn, _target)
                _stats_ok = bool(_chk and _chk["n_reviews"] > 0)
                _others = [n for n in _names if n != _target]

                st.markdown(_selected_card_html(_target, _meta), unsafe_allow_html=True)
                st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

                # ── 分析タイプ選択（2択カード）──────────────────────── #
                _an_type = st.session_state.get("an_analysis_type", "competitor")
                _tc, _tm = st.columns(2)
                with _tc:
                    if st.button(
                        "🎯 指定競合との比較",
                        help="最大5施設を選んで詳細な強み・弱みを比較します",
                        width="stretch",
                        type="primary" if _an_type == "competitor" else "secondary",
                        key="an_type_btn_competitor",
                    ):
                        st.session_state["an_analysis_type"] = "competitor"
                        st.rerun()
                with _tm:
                    if st.button(
                        "📊 マーケット比較",
                        help=f"DB内 {len(_others)} 施設全体との比較で市場ポジションを把握します",
                        width="stretch",
                        type="primary" if _an_type == "market" else "secondary",
                        key="an_type_btn_market",
                    ):
                        st.session_state["an_analysis_type"] = "market"
                        st.rerun()

                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                if _an_type == "competitor":
                    if _others:
                        # デフォルト: DB登録済み比較施設（最大5件）
                        _default_peers = [p for p in
                                          analysis.facilities_by_type(conn, "comparison")
                                          if p in _others][:5]
                        _prev_sel = [p for p in
                                     st.session_state.get("an_peers", _default_peers)
                                     if p in _others][:5]
                        _selected_peers = st.multiselect(
                            "比較施設を選択（最大5件）",
                            options=_others,
                            default=_prev_sel,
                            max_selections=5,
                            key="an_peers_multi",
                            placeholder="施設名を入力して絞り込む...",
                        )
                        st.session_state["an_peers"] = _selected_peers
                        st.session_state["an_mode"] = "compare" if _selected_peers else "single"
                        st.session_state["an_axis_label"] = "比較施設の平均"
                    else:
                        st.info("比較できる施設がありません。単体分析で実行します。")
                        st.session_state["an_mode"] = "single"
                        st.session_state["an_peers"] = []
                else:
                    st.caption(
                        f"比較対象: DB内の全施設（{len(_others)} 施設）"
                        " — 市場全体での順位・スコア分布を表示します"
                    )
                    st.session_state["an_peers"] = _others
                    st.session_state["an_mode"] = "compare"
                    st.session_state["an_axis_label"] = "DB全体の平均"

                # ── LLM キー（任意）─────────────────────────────────── #
                if not llm.get_api_key():
                    with st.expander("Gemini API キー（LLMインサイト、任意）", expanded=False):
                        st.text_input(
                            "Gemini API キー", type="password", key="an_api_key",
                            help="aistudio.google.com で無料取得できます。省略可。",
                            label_visibility="collapsed",
                        )

                # ── レポートの構成 ────────────────────────────────────── #
                #    「（詳細）」の3枚はプランナー向けの掘り下げページ。
                #    相手や場面によっては要らないので、ここで外せるようにする。
                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                _dc1, _dc2, _dc3 = st.columns([1, 2, 1])
                with _dc2:
                    st.toggle(
                        "「詳細」ページも作る",
                        value=st.session_state.get("an_with_detail", True),
                        key="an_with_detail",
                        help="市場内ポジション（詳細）／指定競合との比較（詳細）／"
                             "空間体験分析（詳細）の3枚。オフにすると7枚構成になります。",
                    )
                    _n_slides = len(slides.report_slides(
                        detail=st.session_state.get("an_with_detail", True)))
                    st.caption(f"レポートは全 {_n_slides} 枚（＋冒頭の免責）になります")

                # ── 実行ボタン ────────────────────────────────────────── #
                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
                _rc1, _rc2, _rc3 = st.columns([1, 2, 1])
                with _rc2:
                    if _stats_ok:
                        if st.button("この内容で分析する", type="primary",
                                     width="stretch", key="an_run"):
                            st.session_state["an_screen"] = "running"
                            st.rerun()
                    else:
                        st.warning("この施設には口コミデータがありません。")
                        _kz_collect_section(conn, _target)
                    if st.button("← 施設を選び直す", width="stretch", key="an_reselect"):
                        st.session_state["an_target"] = None
                        st.session_state.pop("an_search", None)
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════ #
    # RUNNING (analysis + report generation)
    # ══════════════════════════════════════════════════════════════════════ #
    elif st.session_state["an_screen"] == "running":
        _target = st.session_state["an_target"]
        _an_mode = st.session_state["an_mode"]

        _fid_row = conn.execute(
            "SELECT id FROM facility WHERE name = ?", (_target,)
        ).fetchone()
        if not _fid_row:
            st.error("施設データが見つかりません。")
            st.stop()
        _fid = _fid_row["id"]

        _api_key = llm.get_api_key() or st.session_state.get("an_api_key", "")
        _an_type = st.session_state.get("an_analysis_type", "competitor")
        _axis = "comparison_avg"
        _specific_name = None
        _peers_for_bundle = None  # None → build_bundle が DB タグ施設を使う
        if _an_mode == "compare":
            _peers_ss = st.session_state.get("an_peers", [])
            _axis_lbl = st.session_state.get("an_axis_label", "比較施設の平均")
            if _an_type == "market" or _axis_lbl == "DB全体の平均":
                _axis = "all_avg"
            elif _an_type == "competitor" and _peers_ss:
                _peers_for_bundle = _peers_ss  # スライドの競合表示を選択施設で上書き
            elif _axis_lbl == "特定施設を指定" and _peers_ss:
                _axis = "specific"
                _specific_name = _peers_ss[0]

        # Hide Streamlit's own chrome so the loading overlay stands completely alone.
        st.markdown(
            "<style>[data-testid='stHeader']{display:none!important;}"
            "[data-testid='stStatusWidget']{display:none!important;}"
            "[data-testid='stToolbar']{display:none!important;}"
            "[data-testid='stAppViewContainer']{opacity:1!important;}</style>",
            unsafe_allow_html=True,
        )

        # ── Progress state key (unique per target so restarting a different
        #    facility doesn't collide with a stale background thread)
        _PROG_KEY = f"_vb_prog_{_target}"
        _prog = st.session_state.get(_PROG_KEY) or {}

        # ── ① 完了 → メインスレッドで session_state に反映してプレビューへ ──
        #    ワーカースレッドには ScriptRunContext が無いため、そこからの
        #    st.session_state への書き込みは Streamlit 内部の捨てられるモックに
        #    落ちて **無言で消える**（1.58 session_state_proxy.get_session_state:
        #    ctx が None ならグローバルの _mock_session_state を返す）。
        #    そのためスレッドは結果を prog["result"]（ただの dict）に置き、
        #    session_state への反映は必ずこのメインスレッド側で行う。
        if _prog.get("done"):
            for _k, _v in (_prog.get("result") or {}).items():
                st.session_state[_k] = _v
            # どの工程に何秒かかったかはプレビュー側で出す（遅いときの切り分け用）
            st.session_state["an_timings"] = _prog.get("timings") or []
            st.session_state["an_screen"] = "preview"
            st.session_state.pop(_PROG_KEY, None)
            st.rerun()

        # ── ② エラー → 内容を出して停止 ─────────────────────────────── #
        if _prog.get("error"):
            st.error("分析中にエラーが発生しました:\n\n```\n" + _prog["error"] + "\n```")
            if st.button("設定に戻る", key="an_err_back"):
                st.session_state["an_screen"] = "setup"
                st.session_state.pop(_PROG_KEY, None)
                st.rerun()
            st.stop()

        # ── ③ 実行中 → fragment が 1 秒ごとに進捗だけを再描画 ──────────── #
        if _prog.get("running"):
            _th = _prog.get("_thread")
            if _th is not None and not _th.is_alive():
                # 上の _prog 読み取り後にスレッドが完走した場合もここに来るので、
                # 実際に done/error が立っているかを取り直してから判定する。
                if not _prog.get("done") and not _prog.get("error"):
                    # どちらも立たずにスレッドが消えた＝異常終了。これが無いと
                    # ローディングカードが永久に回り続ける。
                    _prog["error"] = (
                        "分析スレッドが予期せず終了しました"
                        "（メモリ不足などの可能性があります）。もう一度お試しください。"
                    )
                st.rerun()   # → ①（完了）／②（エラー）が処理する

            @st.fragment(run_every="1s")
            def _progress_ui():
                _p = st.session_state.get(_PROG_KEY) or {}
                if _p.get("done") or _p.get("error"):
                    st.rerun()      # scope="app" → 上の ①／② が処理する
                    return
                _started = _p.get("phase_started")
                st.markdown(
                    _loading_card_html(
                        _p.get("step", 2), _p.get("detail", ""),
                        server_secs=(time.time() - _started) if _started else None,
                    ),
                    unsafe_allow_html=True,
                )

            _progress_ui()

            # 止まったときに待つしかない状態にしない。押せば設定画面へ戻れる。
            # ワーカーには cancelled を立てて、次のチェックポイントで手を引かせる。
            _cc1, _cc2, _cc3 = st.columns([1, 2, 1])
            with _cc2:
                if st.button("■ 分析を中止する", key="an_cancel", width="stretch"):
                    _prog["cancelled"] = True
                    st.session_state["an_screen"] = "setup"
                    st.session_state.pop(_PROG_KEY, None)
                    st.rerun()
                st.caption(
                    "進んだぶん（形態素解析・感情スコア）はDBに残るので、"
                    "やり直しても最初からにはなりません。"
                )
            st.stop()

        # ── ④ 未開始 → 同期ステップ①② を実行してワーカーを起動 ────────── #
        # ── Sync phase: steps ① and ② (fast; ② must be in main thread) ──
        _n_rev = conn.execute(
            "SELECT COUNT(*) FROM review WHERE facility_id = ?", (_fid,)
        ).fetchone()[0]
        _ph0 = st.empty()
        _ph0.markdown(
            _loading_card_html(0, f"「{_target}」の口コミ {_n_rev:,} 件をDBから読み込んでいます"),
            unsafe_allow_html=True,
        )
        _rev_rows = conn.execute(
            "SELECT rating, text FROM review WHERE facility_id = ?", (_fid,)
        ).fetchall()
        _revs = [(_r["rating"], _r["text"] or "") for _r in _rev_rows]
        _n_with_text = sum(1 for _, t in _revs if t.strip())

        _ph0.markdown(
            _loading_card_html(1, f"口コミ {_n_rev:,} 件 ／ 本文あり {_n_with_text:,} 件 — 評点・ポジ率を集計中"),
            unsafe_allow_html=True,
        )
        scoring.compute_and_store(conn, _fid)

        _all_names = _all_facility_names()
        _n_fac = len(_all_names)
        _sig = _topic_sig()
        _prof_key = f"_vb_profile_{_target}_{hash(_sig)}"
        _cached_profile = st.session_state.get(_prof_key)
        # キャッシュ確認は session_state のみ。
        # ここで data.topic_matrix_cached(_sig) を呼んではいけない： @st.cache_data は
        # ミス時に「全施設ぶんを同期計算」するため、ワーカー起動前にメインスレッドを
        # 数分ブロックし、進捗カードが止まったまま固まる。クロスセッションの永続化は
        # DB の topic_score_cache（施設単位・進捗表示あり）が担当する。
        _matrix_ss_key = f"_vb_matrix_{hash(_sig)}"
        _cached_matrix = st.session_state.get(_matrix_ss_key) or None

        # Init shared progress dict (thread writes to this directly)
        _new_prog: dict = {
            "step": 2,
            "detail": f"{_n_fac} 施設のキャッシュを確認中…" if _cached_matrix else
                      f"{_n_fac} 施設・{_n_with_text:,} 件の感情スコアを解析中 (1/{_n_fac})",
            "running": True,
            "done": False,
            "error": None,
            # pass-through for thread
            "_target": _target,
            "_an_mode": _an_mode,
            "_axis": _axis,
            "_specific_name": _specific_name,
            "_api_key": _api_key,
            "_revs": _revs,
            "_n_rev": _n_rev,
            "_n_with_text": _n_with_text,
            "_all_names": _all_names,
            "_prof_key": _prof_key,
            "_cached_profile": _cached_profile,
            "_cached_matrix": _cached_matrix,
            "_matrix_ss_key": _matrix_ss_key,
            "_peers_for_bundle": _peers_for_bundle,
            "_db_path": None,   # None → 既定のDB/Turso（テストから差し替え可能）
            "cancelled": False,
        }

        # 別施設の分析が走ったままだと、ワーカーが2本同時に動いて CPU を食い合ううえ、
        # janome のトークナイザを取り合って解析が壊れる原因にもなる。
        # Python のスレッドは外から止められないので、中止フラグを立てて
        # 次の区切りで自分から抜けてもらう。
        for _k in [k for k in st.session_state if k.startswith("_vb_prog_")]:
            if _k == _PROG_KEY:
                continue
            _old = st.session_state.get(_k)
            if isinstance(_old, dict) and _old.get("running") and not _old.get("done"):
                _old["cancelled"] = True
            st.session_state.pop(_k, None)

        st.session_state[_PROG_KEY] = _new_prog

        _thread = threading.Thread(
            target=_analysis_worker, args=(_new_prog,), daemon=True
        )
        _thread.start()
        _new_prog["_thread"] = _thread   # ③ の生存監視で使う
        _ph0.empty()
        st.rerun()   # → ③ に入り、以後は fragment が進捗を描画する

    # ══════════════════════════════════════════════════════════════════════ #
    # PREVIEW SCREEN — analysis result rendered as stacked slides
    # ══════════════════════════════════════════════════════════════════════ #
    elif st.session_state["an_screen"] == "preview":
        _target = st.session_state["an_target"]
        _result_path = st.session_state.get("an_result_path")
        _bundle = st.session_state.get("an_preview")
        _ts = st.session_state.get("an_topic_score")

        # ── Top bar: back (left) + download (right) ─────────────────────── #
        _hc1, _hc2 = st.columns([1, 1])
        with _hc1:
            if st.button("← 設定に戻る", key="an_back_top", width="stretch"):
                st.session_state["an_screen"] = "setup"
                st.rerun()
        with _hc2:
            if _result_path and Path(_result_path).exists():
                with open(_result_path, "rb") as _f:
                    st.download_button(
                        "⬇ PowerPointでダウンロード",
                        data=_f.read(),
                        file_name=Path(_result_path).name,
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".presentationml.presentation"
                        ),
                        type="primary",
                        width="stretch",
                        key="an_dl",
                    )
            else:
                st.error("レポートファイルが見つかりません。設定に戻って再実行してください。")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── Stacked 16:10 slide canvases ────────────────────────────────── #
        if _bundle:
            # ── PROFILE 情報を上書き（住所自動取得＋写真＋手入力）──────── #
            _prof = st.session_state.setdefault("an_profile", {}).setdefault(_target, {})
            _fid_row = conn.execute("SELECT id FROM facility WHERE name = ?", (_target,)).fetchone()
            _fid = _fid_row["id"] if _fid_row else None

            if not _prof.get("_enriched"):   # 初回のみ自動補完（OSM/Overpass/Wikidata・キャッシュ済）
                with st.spinner("施設情報（住所・アクセス・開業）を取得中…"):
                    _en = geocode.enrich(_target)
                for _ek in ("address", "access", "open_year"):
                    if _en.get(_ek) and not _prof.get(_ek):
                        _prof[_ek] = _en[_ek]
                if _en.get("category"):
                    _prof["category_auto"] = _en["category"]
                # 延床はOSM等に無い純粋な手入力項目 → DB保存値（facility.floor_area）を初期値に
                if not _prof.get("floor_area") and _fid:
                    _fa_row = conn.execute(
                        "SELECT floor_area FROM facility WHERE id = ?", (_fid,)
                    ).fetchone()
                    if _fa_row and _fa_row["floor_area"]:
                        _prof["floor_area"] = _fa_row["floor_area"]
                _prof["_enriched"] = True
            if _prof.get("address"):
                _bundle["address"] = _prof["address"]
            if _prof.get("access"):
                _bundle["access"] = _prof["access"]
            if _prof.get("open_year"):
                _bundle["open_year"] = _prof["open_year"]
            if _prof.get("floor_area"):
                _bundle["floor_area"] = _prof["floor_area"]
            # 業種: 手入力 > DB > OSM。DBが空のときだけ OSM で補完
            if _prof.get("category"):
                _bundle["category"] = _prof["category"]
            elif (not _bundle.get("category") or _bundle["category"] == "—") and _prof.get("category_auto"):
                _bundle["category"] = _prof["category_auto"]

            # 写真: セッション（今アップ）優先 → 無ければ DB 保存分（キャッシュ読込）
            _photo_bytes = _prof.get("photo_bytes")
            _photo_mime = _prof.get("mime", "image/jpeg")
            if not _photo_bytes and _fid:
                _stored = _photo_from_db(_fid, db.photo_updated_at(conn, _fid))
                if _stored:
                    _photo_bytes, _photo_mime = _stored
            if _photo_bytes:
                _bundle["photo_data_uri"] = (
                    f"data:{_photo_mime};base64," + base64.b64encode(_photo_bytes).decode()
                )

            # ── 空いている写真枠を Google Places で埋める（画面プレビュー専用）──
            #    規約上、写真は保存できない（無期限保存が許されているのは
            #    place_id だけ）。なので DB には焼かず、表示のたびに Google の
            #    URL を <img src> で参照する。PPTX には入らない。
            _places_photos(conn, _bundle)

            # 遅いときの切り分け用。どの工程に何秒かかったかを畳んで出しておく。
            _tm = st.session_state.get("an_timings") or []
            if _tm:
                with st.expander(
                    f"⏱ 処理時間の内訳（合計 {sum(s for _p, s in _tm):,.0f} 秒）",
                    expanded=False,
                ):
                    st.dataframe(
                        pd.DataFrame(_tm, columns=["工程", "秒"]),
                        hide_index=True, width="stretch",
                    )

            st.markdown(slides.slide0_disclaimer(_bundle), unsafe_allow_html=True)

            # ── PROFILE：この場でインライン編集（写真アップ＋各項目の手入力）──── #
            _ekey = f"prof_editing_{_target}"
            _ka, _kacc, _kopen, _kcat, _kfa = (f"prof_addr_{_target}", f"prof_acc_{_target}",
                                               f"prof_open_{_target}", f"prof_cat_{_target}",
                                               f"prof_floor_{_target}")
            if _kcat not in st.session_state:
                _init_cat = _bundle.get("category")
                if not _init_cat or _init_cat == "—":
                    _init_cat = _prof.get("category_auto") or ""
                st.session_state[_kcat] = "" if (not _init_cat or _init_cat == "—") else _init_cat
            for _k, _v in ((_ka, _prof.get("address")), (_kacc, _prof.get("access")),
                           (_kopen, _prof.get("open_year")), (_kfa, _prof.get("floor_area"))):
                if _k not in st.session_state and _v:
                    st.session_state[_k] = _v

            if st.session_state.get(_ekey):
                with st.container(border=True):
                    st.markdown(
                        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
                        f'<span style="font-size:11px;font-weight:800;letter-spacing:.06em;color:#fff;'
                        f'background:{ACCENT};padding:4px 10px;border-radius:6px;">PROFILE 編集</span>'
                        '<span style="font-size:15px;font-weight:800;color:#16202B;">写真アップロードと情報の書き込み</span></div>',
                        unsafe_allow_html=True,
                    )
                    _ecol1, _ecol2 = st.columns([2, 3], gap="large")
                    with _ecol1:
                        _up = st.file_uploader("施設写真（自動で長辺1200px/JPEGに縮小）",
                                               type=["png", "jpg", "jpeg", "webp"],
                                               key=f"prof_photo_{_target}")
                        if _up is not None:
                            _rz, _mime = images.resize_for_storage(_up.getvalue())
                            _prof["photo_bytes"] = _rz
                            _prof["mime"] = _mime
                            _photo_bytes, _photo_mime = _rz, _mime
                        if _photo_bytes:
                            st.image(_photo_bytes, width="stretch")
                        else:
                            st.markdown(
                                '<div style="aspect-ratio:1;border-radius:12px;background:#F1F0EA;'
                                'display:flex;align-items:center;justify-content:center;color:#A7ABB0;">施設写真</div>',
                                unsafe_allow_html=True)
                        _has_db_photo = bool(_fid and db.photo_updated_at(conn, _fid))
                        _b1, _b2 = st.columns(2)
                        with _b1:
                            if st.button("💾 保存", key=f"prof_save_{_target}",
                                         disabled=not _fid, width="stretch",
                                         help="写真と延床をDB/Turso に永続化します"):
                                if _photo_bytes:
                                    db.save_photo(conn, _fid, _photo_bytes, _photo_mime)
                                    _photo_from_db.clear()
                                if _prof.get("floor_area"):
                                    db.upsert_facility(conn, _target, floor_area=_prof["floor_area"])
                                st.success("DBに保存しました。")
                                st.rerun()
                        with _b2:
                            if st.button("🗑️ 削除", key=f"prof_del_{_target}",
                                         disabled=not _has_db_photo, width="stretch"):
                                db.delete_photo(conn, _fid)
                                _prof.pop("photo_bytes", None)
                                _photo_from_db.clear()
                                st.success("削除しました。")
                                st.rerun()
                        st.caption("💾 DB保存済み" if _has_db_photo else "未保存（保存で Turso/DB に永続化）")
                    with _ecol2:
                        st.text_input("施設名", value=_target, disabled=True, key=f"prof_name_{_target}")
                        _prof["category"] = st.text_input("業種", key=_kcat, placeholder="例: 美術館・博物館")
                        _prof["address"] = st.text_input("住所", key=_ka)
                        _prof["access"] = st.text_input("アクセス", key=_kacc, placeholder="例: 〇〇駅 徒歩約5分")
                        _prof["open_year"] = st.text_input("開業", key=_kopen, placeholder="例: 2015年")
                        _prof["floor_area"] = st.text_input("延床", key=_kfa, placeholder="例: 28,500㎡",
                                                            help="外部データ源が無いため手入力のみ（💾保存でDBに永続化）")
                        if st.button("🗺️ 自動取得（OSM／Wikidata）", key=f"prof_geo_{_target}",
                                     width="stretch",
                                     help="住所・アクセス・業種=OpenStreetMap、開業=Wikidata（生成AI不使用）"):
                            with st.spinner("OpenStreetMap / Overpass / Wikidata で検索中…"):
                                _en = geocode.enrich(_target)
                            _got = []
                            if _en.get("address"):
                                st.session_state[_ka] = _en["address"]; _got.append("住所")
                            if _en.get("access"):
                                st.session_state[_kacc] = _en["access"]; _got.append("アクセス")
                            if _en.get("open_year"):
                                st.session_state[_kopen] = _en["open_year"]; _got.append("開業")
                            if _en.get("category"):
                                st.session_state[_kcat] = _en["category"]; _got.append("業種")
                            if _got:
                                st.success("取得しました: " + "・".join(_got))
                                st.rerun()
                            else:
                                st.warning("該当が見つかりませんでした（施設名が長い／通信不可の可能性）。手入力してください。")
                        st.caption("※ 生成AIは不使用。取れない項目は手入力してください。")
                    _a1, _a2 = st.columns(2)
                    with _a1:
                        if st.button("📄 この内容でPPTXを更新", type="primary",
                                     width="stretch", key=f"prof_regen_{_target}"):
                            _info = {"address": _prof.get("address"), "access": _prof.get("access"),
                                     "open_year": _prof.get("open_year"),
                                     "category": _prof.get("category") or _bundle.get("category"),
                                     "floor_area": _prof.get("floor_area")}
                            with st.spinner("PPTXを再生成中…"):
                                _tmp2 = Path(tempfile.mkdtemp()) / f"VoiceBAUM_{_target}.pptx"
                                report.build_report(
                                    conn, _target,
                                    axis=st.session_state.get("an_axis", "comparison_avg"),
                                    specific_name=st.session_state.get("an_specific_name"),
                                    insights=st.session_state.get("insights"),
                                    topic_list=st.session_state.get("an_topic_list") or None,
                                    topic_score_result=st.session_state.get("an_topic_score"),
                                    profile_info=_info, photo_bytes=_photo_bytes,
                                    peers=st.session_state.get("an_peers_used"),
                                    output_path=_tmp2)
                            st.session_state["an_result_path"] = str(_tmp2)
                            st.success("レポートを更新しました。上部のダウンロードから取得してください。")
                            st.rerun()
                    with _a2:
                        if st.button("✓ 編集を終える（プレビューに戻る）", width="stretch",
                                     key=f"prof_done_{_target}"):
                            st.session_state[_ekey] = False
                            st.rerun()
            else:
                st.markdown(slides.slide1_facility_info(_bundle), unsafe_allow_html=True)
                _pe1, _pe2, _pe3 = st.columns([1, 1.4, 1])
                with _pe2:
                    if st.button("✏️ PROFILEを編集（写真・住所など）", width="stretch",
                                 key=f"prof_edit_btn_{_target}"):
                        st.session_state[_ekey] = True
                        st.rerun()

            # ── 分析レポート本体（PDF「20260726_VoiceBAUM_v1」p3〜p12 準拠）──── #
            #    SLIDE 1 は上の PROFILE 編集ブロック側で描いている（編集中は
            #    フォームに差し替わるため）。ここは SLIDE 2 以降。
            for _slide in slides.report_slides(
                detail=st.session_state.get("an_with_detail", True)
            )[1:]:                       # SLIDE 1 は上の PROFILE ブロックで描画済み
                st.markdown(_slide(_bundle), unsafe_allow_html=True)
        else:
            st.warning("分析結果がありません。設定に戻って再実行してください。")

        # ── Details (topic score table / LLM insights) ─────────────────── #
        if _ts is not None and not _ts.empty:
            with st.expander("🧭 トピックスコアの詳細（言及度・統合スコア・重み）", expanded=False):
                _df = pd.DataFrame([
                    {
                        "トピック（指標軸）": t.name,
                        "感情スコア": round(t.sentiment_100, 1),
                        "言及度(%)": round(t.salience_pct, 1),
                        "統合スコア": round(t.avg_score, 4),
                        "重み": round(t.weight, 3),
                    }
                    for t in _ts.sorted_by_sentiment()
                ])
                st.dataframe(_df, width="stretch", hide_index=True)
                st.plotly_chart(
                    charts.topic_salience_bar(_ts), width="stretch", key="an_ts_sal"
                )
                st.caption(f"モデル全体スコア Σ(avg×重み) = {_ts.overall_100} / 100")

        insights = st.session_state.get("insights")
        if insights and st.session_state.get("insights_facility") == _target:
            with st.expander("✨ LLMインサイト（全文）", expanded=False):
                st.markdown(f"**まとめ**: {insights.summary}")
                _ic1, _ic2 = st.columns(2)
                with _ic1:
                    st.markdown("**💪 強み**")
                    for item in insights.strengths:
                        st.markdown(f"- {item}")
                with _ic2:
                    st.markdown("**⚠️ 弱み**")
                    for item in insights.weaknesses:
                        st.markdown(f"- {item}")
                if insights.implications:
                    st.markdown("**💡 示唆**")
                    for item in insights.implications:
                        st.markdown(f"- {item}")
                if insights.improvements:
                    st.markdown("**🔧 改善提案**")
                    for item in insights.improvements:
                        st.markdown(f"- {item}")

        st.divider()
        if st.button("← 設定に戻って別の施設を分析する", key="an_back_main"):
            st.session_state["an_screen"] = "setup"
            st.rerun()
