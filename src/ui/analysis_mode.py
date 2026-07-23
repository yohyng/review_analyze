"""Analysis-mode screens (setup / running / preview) for VoiceBAUM.

Extracted from app.py. render() is called once per Streamlit rerun when
app_mode == "analysis".
"""
from __future__ import annotations

import base64
import os
import tempfile
import time
from html import escape
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src import (
    analysis, auth, charts, config, csv_profiler, db, geocode, images, kaizode,
    llm, preview, report, review_csv, score_excel, scoring, search,
    text_analysis, topic_score, topics,
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


def _kz_progress_tracker(conn, key: str, dataset_id: str, facility_name: str, query: str) -> None:
    """進捗トラッキング画面。自動で status をチェックして進捗を表示。"""
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
        if _kz_pull(conn, key, query):
            return
        # 取り込み失敗時は再試行ボタンを出す
        if st.button("⬇️ 取り込みを再度試す", key="an_kz_retry_import", width="stretch"):
            _kz_pull(conn, key, query)
            return

    elif status == 40:
        st.error("❌ 収集に失敗しました。別の施設名を試すか、管理者に連絡してください。")
        return

    # ── 自動更新トリガー ────────────────────── #
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    if st.button("🔄 今すぐ確認", key="an_kz_check_now", width="stretch"):
        st.rerun()

    # 3秒後に自動 rerun
    import time
    time.sleep(3)
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

    _pkey = f"an_kz_preview::{_facility_name}"
    if _pkey not in st.session_state:
        with st.spinner("施設情報を取得中…"):
            _profile = geocode.lookup(_facility_name)
        st.session_state[_pkey] = _profile or {}

    _profile = st.session_state.get(_pkey) or {}
    _addr = (_profile.get("address") or "")[:60] if _profile else "(情報なし)"

    # 見た目を整える
    _pc1, _pc2 = st.columns([3, 1])
    with _pc1:
        st.caption(f"🏢 {_facility_name}  ·  {_addr}")
    with _pc2:
        if st.button("📡 今すぐ集める", key="an_kz_order", type="primary", width="stretch"):
            _maps_url = _parsed_name and _inp or kaizode.maps_search_url(_facility_name)
            _dsid = _kz_order(conn, key, _maps_url, _facility_name)
            if _dsid:
                st.session_state[_ongoing_key] = {
                    "dataset_id": _dsid,
                    "facility_name": _facility_name,
                }
                st.rerun()


def render():
    conn = data.get_conn()
    _all_facility_names = data.all_facility_names
    _facility_card = components.facility_card
    _loading_card_html = components.loading_card_html
    _review_counts = data.review_counts
    _facility_meta = data.facility_meta
    _selected_card_html = components.selected_card_html
    _topic_sig = data.topic_sig
    _topic_matrix_cached = data.topic_matrix_cached
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
        st.markdown("""
        <style>
        div[data-testid="stTextInput"] input{
          height:60px!important;font-size:18px!important;border-radius:15px!important;
          border:1.5px solid #E4E3DD!important;background-color:#fff!important;
          padding-left:52px!important;color:#16202B!important;
          box-shadow:0 1px 2px rgba(20,30,40,.04),0 12px 30px rgba(20,30,40,.05)!important;
          background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='22' height='22' viewBox='0 0 24 24' fill='none' stroke='%23B0338A' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='M21 21l-4.3-4.3'/%3E%3C/svg%3E")!important;
          background-repeat:no-repeat!important;background-position:18px center!important;background-size:22px 22px!important;
        }
        div[data-testid="stTextInput"] input:focus{
          border-color:#B0338A!important;box-shadow:0 0 0 4px rgba(176,51,138,.18)!important;}
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
                # ── 選択済み：施設カード + 分析ボタン（ネイティブ）─────── #
                _chk = db.facility_stats(conn, _target)
                _stats_ok = bool(_chk and _chk["n_reviews"] > 0)

                st.markdown(_selected_card_html(_target, _meta), unsafe_allow_html=True)
                st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

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

                # 比較分析・LLM は詳細オプション（既定は畳んでおく）
                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
                with st.expander("詳細オプション（比較分析・LLMインサイト）", expanded=False):
                    _mode = st.radio(
                        "分析タイプ", ["🏠 単体で分析", "🆚 比較分析"],
                        horizontal=True, key="an_mode_radio",
                    )
                    st.session_state["an_mode"] = "single" if "単体" in _mode else "compare"
                    if st.session_state["an_mode"] == "compare":
                        _others = [n for n in _names if n != _target]
                        if _others:
                            _axis_label = st.radio(
                                "比較基準", ["比較施設の平均", "DB全体の平均", "特定施設を指定"],
                                key="an_axis_label",
                            )
                            if _axis_label == "特定施設を指定":
                                _spec = st.selectbox("比較先", _others, key="an_specific")
                                st.session_state["an_peers"] = [_spec] if _spec else []
                            elif _axis_label == "比較施設の平均":
                                _peers = analysis.facilities_by_type(conn, "comparison")
                                st.session_state["an_peers"] = _peers
                                if _peers:
                                    st.caption(f"比較対象: {', '.join(_peers)}")
                                else:
                                    st.warning("「比較施設」種別の施設がありません。DB全体平均で代替します。")
                            else:
                                st.session_state["an_peers"] = _others
                                st.caption(f"比較対象: DB内の全施設（{len(_others)} 施設）")
                        else:
                            st.info("比較できる他の施設がありません。単体分析で実行します。")
                            st.session_state["an_mode"] = "single"
                    else:
                        st.session_state["an_peers"] = []
                    if not llm.get_api_key():
                        st.text_input(
                            "Gemini API キー（任意）", type="password", key="an_api_key",
                            help="aistudio.google.com で無料取得できます。省略可。",
                        )

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
        _axis = "comparison_avg"
        _specific_name = None
        if _an_mode == "compare":
            _peers_ss = st.session_state.get("an_peers", [])
            _axis_lbl = st.session_state.get("an_axis_label", "比較施設の平均")
            if _axis_lbl == "DB全体の平均":
                _axis = "all_avg"
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

        _n_rev = conn.execute(
            "SELECT COUNT(*) FROM review WHERE facility_id = ?", (_fid,)
        ).fetchone()[0]

        _ph = st.empty()

        def _show(cur, detail=""):
            _ph.markdown(_loading_card_html(cur, detail), unsafe_allow_html=True)

        # ① 口コミデータを収集中
        _show(0, f"口コミ {_n_rev:,} 件を読み込んでいます")
        _rev_rows = conn.execute(
            "SELECT rating, text FROM review WHERE facility_id = ?", (_fid,)
        ).fetchall()
        _revs = [(_r["rating"], _r["text"] or "") for _r in _rev_rows]

        # ② 評価スコアを集計中
        _show(1, f"口コミ {_n_rev:,} 件のスコアを集計中")
        scoring.compute_and_store(conn, _fid)

        # ③ ポジ／ネガの感情を分析中  ← 22観点の感情・トピック統合スコア（全施設）
        _n_fac = len(_all_facility_names())
        _show(2, f"{_n_fac} 施設・{_n_rev:,} 件の感情／トピックを解析中（時間がかかる場合があります）")
        _profile = text_analysis.build_profile(conn, _target, top_n=20)
        _topic_matrix = _topic_matrix_cached(_topic_sig())
        _ts_result = _topic_matrix.get(_target) or topic_score.analyze_facility(conn, _target)

        # ④ トピックを分類中（TF-IDF）  ← SLIDE 04 用
        _show(3, f"{_ts_result.n_sentences:,} 文の特徴語を抽出中")
        _topic_list = topics.extract_topics(_revs, n_topics=5)

        # ⑤ 競合と比較中（＋任意でLLMインサイト）
        _show(4, "競合施設と比較中")
        _insights = None
        if _api_key and not _profile.empty:
            _comp2 = (
                analysis.build_comparison(conn, _target, _axis, specific_name=_specific_name)
                or analysis.build_comparison(conn, _target, "all_avg")
            )
            _diff = _comp2.diff if _comp2 else None
            _kw = _profile.tfidf_keywords["単語"].tolist()
            _bi = (
                _profile.bigrams["フレーズ"].tolist()
                if not _profile.bigrams.empty else []
            )
            _prompt = llm.build_prompt(
                _target, _diff, _kw, _bi, _profile.high_rated, _profile.low_rated
            )
            _res = llm.generate_insights(_prompt, _api_key)
            if not _res.error:
                _insights = _res

        # ⑥ レポートを生成中
        _show(5, "PowerPointレポートを生成中")
        _tmp = Path(tempfile.mkdtemp()) / f"VoiceBAUM_{_target}.pptx"
        report.build_report(
            conn, _target,
            axis=_axis if _an_mode == "compare" else "comparison_avg",
            specific_name=_specific_name,
            insights=_insights,
            topic_list=_topic_list if _topic_list else None,
            topic_score_result=_ts_result if not _ts_result.empty else None,
            output_path=_tmp,
        )

        _show(6, "完了しました")  # all steps complete

        # Build the preview bundle now (so preview reruns stay instant)
        st.session_state["an_preview"] = preview.build_bundle(
            conn, _target, _topic_matrix, _profile, _insights,
        )
        st.session_state["an_result_path"] = str(_tmp)
        st.session_state["an_topic_list"] = _topic_list
        st.session_state["an_topic_score"] = _ts_result
        st.session_state["analysis_target"] = _target
        st.session_state["insights"] = _insights
        st.session_state["insights_facility"] = _target
        st.session_state["an_axis"] = _axis if _an_mode == "compare" else "comparison_avg"
        st.session_state["an_specific_name"] = _specific_name
        st.session_state["an_screen"] = "preview"
        st.rerun()

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
                _prof["_enriched"] = True
            if _prof.get("address"):
                _bundle["address"] = _prof["address"]
            if _prof.get("access"):
                _bundle["access"] = _prof["access"]
            if _prof.get("open_year"):
                _bundle["open_year"] = _prof["open_year"]
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

            st.markdown(preview.html_disclaimer(_bundle), unsafe_allow_html=True)
            st.markdown(preview.html_overview(_bundle), unsafe_allow_html=True)

            # ── PROFILE：この場でインライン編集（写真アップ＋各項目の手入力）──── #
            _ekey = f"prof_editing_{_target}"
            _ka, _kacc, _kopen, _kcat = (f"prof_addr_{_target}", f"prof_acc_{_target}",
                                         f"prof_open_{_target}", f"prof_cat_{_target}")
            if _kcat not in st.session_state:
                _init_cat = _bundle.get("category")
                if not _init_cat or _init_cat == "—":
                    _init_cat = _prof.get("category_auto") or ""
                st.session_state[_kcat] = "" if (not _init_cat or _init_cat == "—") else _init_cat
            for _k, _v in ((_ka, _prof.get("address")), (_kacc, _prof.get("access")),
                           (_kopen, _prof.get("open_year"))):
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
                                         disabled=not (_photo_bytes and _fid), width="stretch"):
                                db.save_photo(conn, _fid, _photo_bytes, _photo_mime)
                                _photo_from_db.clear()
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
                                     "category": _prof.get("category") or _bundle.get("category")}
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
                st.markdown(preview.html_profile(_bundle), unsafe_allow_html=True)
                _pe1, _pe2, _pe3 = st.columns([1, 1.4, 1])
                with _pe2:
                    if st.button("✏️ PROFILEを編集（写真・住所など）", width="stretch",
                                 key=f"prof_edit_btn_{_target}"):
                        st.session_state[_ekey] = True
                        st.rerun()

            st.markdown(preview.html_slide01(_bundle), unsafe_allow_html=True)
            st.markdown(preview.html_slide02(_bundle), unsafe_allow_html=True)
            st.markdown(preview.html_slide03(_bundle), unsafe_allow_html=True)
            st.markdown(preview.html_slide04(_bundle), unsafe_allow_html=True)
            _appendix_html = preview.html_appendix(_bundle)
            if _appendix_html:
                st.markdown(_appendix_html, unsafe_allow_html=True)
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
