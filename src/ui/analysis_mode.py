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

from .markup import html as _html

from src import (
    analysis, auth, charts, config, csv_profiler, db, geocode, images, kaizode,
    llm, maps_link, onboard, places, precheck, preview, rare, report, report_v5,
    review_csv,
    score_excel, scoring, search,
    discussion, slides, text_analysis, timeline, topic_score, topics, vffi,
    voices,
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


@st.cache_data(ttl=1800, show_spinner="Google で施設を検索中…")
def _gmaps_candidates(query: str, api_key: str) -> list:
    """候補検索のキャッシュ。**素で呼ばないこと**。

    Streamlit は操作のたびにスクリプト全体を再実行する。キャッシュしないと
    ボタンを押すたび・入力欄を触るたびに Google に1回ずつ課金される
    （しかも件数つきの検索は上のSKU階層に入る可能性が高い）。
    api_key を引数に含めるのはキーを変えたら引き直すため。
    """
    return places.search_candidates(query, api_key)


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


def _ftype(role: str) -> str:
    return "comparison" if role == "peer" else "target"


def _collect_label(role: str) -> str:
    # 細い列で2行に折れないよう短くする。何が起きるかは下の注記に書く。
    if role == "peer":
        return "集めて比較施設に追加"
    return "集めて分析する"


def _collect_note(role: str, remaining: int, reuse=None) -> str:
    if reuse is not None:
        # 既存の収集を使うときは発注しない。「収集」と書くと二重発注に見える。
        done = reuse.get("status") == kaizode.STATUS_DONE
        first = "取り込み" if done else "収集の完了を待って取り込み"
        last = "比較施設に追加します" if role == "peer" else "分析まで自動で進みます"
        return f"押すと、{first} → {last}（新しい発注はしません）"
    if role == "peer":
        return (f"押すと、施設を登録 → 口コミを収集 → 取り込み → 比較施設に"
                f"追加します（残枠 {remaining:,} 件）")
    return (f"押すと、施設を登録 → 口コミを収集 → 取り込み → 分析まで"
            f"自動で進みます（残枠 {remaining:,} 件）")


PEER_SEARCH = "an_peer_search"
PEER_NONCE = "an_peer_search_nonce"
PEERS_KEY = "an_peers"
PEERS_WIDGET = "an_peers_multi"
MAX_PEERS = 5


def peer_widget_key() -> str:
    """比較施設の multiselect のキー。**追加のたびに変える**。

    `an_peers` を書き換えても、同じ key のウィジェットは前の値に戻る。
    session_state からキーを消しても駄目で、st.rerun() はフロント側が
    持っているウィジェットの値をそのまま送り直してくる。
    key 自体を変えて**別のウィジェットにする**しかない。

    追従しないとどうなるか: multiselect が古い値（空）を返し、直後の
    `an_peers = _selected_peers` がそれで上書きするので、
    **足した比較施設がその場で消える**。
    """
    return f"{PEERS_WIDGET}_{int(st.session_state.get(PEER_NONCE, 0))}"


def add_peer(name: str) -> bool:
    """比較施設に1件足す。足せたら True。"""
    name = (name or "").strip()
    if not name:
        return False
    peers = list(st.session_state.get(PEERS_KEY) or [])
    if name in peers or len(peers) >= MAX_PEERS:
        return False
    peers.append(name)
    st.session_state[PEERS_KEY] = peers
    st.session_state["an_mode"] = "compare"
    # 検索欄と multiselect を組み直させるため、次の描画では別の key にする
    st.session_state[PEER_NONCE] = int(st.session_state.get(PEER_NONCE, 0)) + 1
    return True


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
            _ong = st.session_state.get(f"an_kz_ongoing::{query}") or {}
            if _ong.get("role") == "peer":
                # 比較施設として集めた場合は、**分析対象を差し替えない**。
                # 選択中の比較施設に足して、設定画面に留まる。
                st.session_state.pop(f"an_kz_ongoing::{query}", None)
                add_peer(query)
                st.success(f"✅ 「{query}」を比較施設に追加しました。")
                st.rerun()
                return True
            st.session_state["an_target"] = query
            # 「集めて分析する」から始めた場合は、取り込んだらそのまま分析へ。
            # ここで止めると、待った末にもう一度ボタンを押させることになる。
            if _ong.get("auto_analyze"):
                st.session_state.pop(f"an_kz_ongoing::{query}", None)
                st.session_state["an_screen"] = "running"
            else:
                st.success(f"✅ 「{query}」の口コミを取り込みました。分析できます。")
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
        _html("<div style='height:8px'></div>")
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
    _html("<div style='height:6px'></div>")
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
    _html("<div style='height:10px'></div>")

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

    # ── 進行中の収集があれば、そちらを優先表示 ────────────────── #
    _ongoing_key = f"an_kz_ongoing::{query}"
    _ongoing = st.session_state.get(_ongoing_key)
    if _ongoing:
        _kz_progress_tracker(conn, key, _ongoing["dataset_id"], _ongoing["facility_name"], query)
        return

    # ── STEP 1: 対象の確定 ────────────────────────────────────── #
    #   ここに来る時点で施設は選ばれている。**打ち直させない。**
    #   以前は空の入力欄を出していたので、ヒーロー画面で名前を入れた人が
    #   同じ名前をもう一度打つことになっていた。
    #   URL で指し直したい人のためだけに、畳んだ欄を残す。
    #
    #   key は施設名ごとに分ける。使い回すとウィジェットが前の施設の値を
    #   復元して、別の施設に発注してしまう（session_state から消しても戻る）。
    _ikey = f"an_kz_url_input::{query}"
    with st.expander("URL で指定し直す（同名の別施設を避けたいとき）",
                     expanded=False):
        _ovr = st.text_input(
            "Google マップの URL",
            key=_ikey,
            placeholder="例: https://www.google.com/maps/place/...",
        )
    _inp = (_ovr or "").strip() or query

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

    # ── STEP 2: 取れそうかの判定（1枚） ─────────────────────── #
    _disp = (_resolved.get("name") if _resolved else "") or _facility_name
    _probe = _kz_probe(conn, key, _facility_name)
    _pf = precheck.build(
        facility=_disp,
        # URL を貼られたときは、その URL が1件を指している（作り直さない）
        place_id=((_resolved or {}).get("place_id") or ("url" if _typed_url else "")),
        review_count=None,      # resolve は件数を返さない（安い SKU のため）
        remaining=kaizode.monthly_remaining(conn),
        limit=kaizode.monthly_limit(conn),
        already=onboard._review_count(conn, _facility_name),
        known_count=(_probe.known_count if _probe else None),
    )
    _reuse = _reusable(_probe)
    _html(_judgement_card(_pf, _probe, _disp,
                          "" if _addr == "(情報なし)" else _addr))

    if _pf.blocked:
        st.button("枠が足りません", disabled=True, width="stretch",
                  key="an_kz_order_blocked")
    elif st.button(_go_label("target", _reuse) if _reuse
                   else "この条件で取得して分析する",
                   key="an_kz_order", type="primary", width="stretch"):
        # 既存の収集があれば発注しない（二重発注を避ける）
        _dsid = (_reuse.get("dataset_id") if _reuse
                 else _kz_order(conn, key, _maps_url, _facility_name))
        if _dsid:
            # 確定した place_id は覚えておく（保存が許されている唯一のもの）
            if _resolved and _resolved.get("place_id"):
                db.set_place_id(conn, _facility_name, _resolved["place_id"])
            st.session_state[_ongoing_key] = {
                "dataset_id": _dsid,
                "facility_name": _facility_name,
            }
            st.rerun()
    _refresh_controls(key, _facility_name, _probe, _reuse, "section")


def _peer_add_panel(conn, names: list, target: str, selected: list) -> None:
    """比較施設を、対象施設と同じ道筋で足す。

    これまでは **DBに入っている施設からしか選べなかった**。対象施設のほうは
    「名前かURLを入れる → 口コミの有無を見る → 候補を選ぶ → 確認して集める」
    まで通っているのに、比較施設だけ手前で止まっていた。
    同じ onboard.plan / _collect_flow に載せて、判定から取得まで揃える。

    対象施設と違うのは着地点だけ:
      - すでに口コミがある     → その場で比較施設に追加
      - 無い / DBにない       → 収集して、取り込めたら比較施設に追加
      - 分析画面には遷移しない（設定を続けている最中なので）
    """
    if len(selected) >= MAX_PEERS:
        st.caption(f"比較施設は最大 {MAX_PEERS} 件です。")
        return

    # 追加した直後は検索欄を空に戻す。残しておくと、次に開いたときに
    # 前の施設名でまた検索が走る（候補検索は課金される）。
    #   session_state からキーを消すだけでは戻らない。ウィジェットは
    #   自前の状態を持っていて、同じ key なら前の値を復元する。
    #   **key ごと変える**（＝別のウィジェットにする）のが確実。
    _nonce = int(st.session_state.get(PEER_NONCE, 0))
    _box = f"{PEER_SEARCH}_{_nonce}"
    # Enter を押すと再実行されるので、expanded=False のままだと
    # **検索するたびにパネルが閉じる**。入力が残っている間は開けておく。
    _expanded = (bool((st.session_state.get(_box) or "").strip())
                 or bool(st.session_state.pop("an_peer_reopen", False)))

    with st.expander("➕ 比較施設を探して追加（DBに無い施設も）",
                     expanded=_expanded):
        _q = st.text_input(
            "施設名 または Google マップのURL",
            key=_box,
            placeholder="施設名、または Google マップのURL（Enterで検索）",
        )
        _qs = (_q or "").strip()
        if not _qs:
            return
        if _qs == target:
            st.warning("分析対象と同じ施設です。")
            return
        if _qs in selected:
            st.info(f"「{_qs}」はすでに比較施設に入っています。")
            return

        _plan = onboard.plan(conn, _qs, names=names,
                             gmaps_key=places.get_api_key())

        # すでに口コミがある → 集めずに足すだけ
        if _plan.action == onboard.READY:
            st.success(f"「{_plan.facility}」は口コミ {_plan.n_reviews:,} 件あります。")
            if st.button(f"「{_plan.facility}」を比較施設に追加",
                         type="primary", width="stretch", key="an_peer_add_ready"):
                if add_peer(_plan.facility):
                    st.session_state["an_peer_reopen"] = True
                    st.rerun()
                else:
                    st.warning("追加できませんでした（上限か、すでに選択済み）。")
            return

        if _plan.action == onboard.AMBIGUOUS:
            st.caption("どの施設ですか？")
            for _n in _plan.candidates:
                if st.button(_n, key=f"an_peer_sug_{_n}", width="stretch"):
                    if add_peer(_n):
                        st.session_state["an_peer_reopen"] = True
                        st.rerun()
            return

        if _plan.action == onboard.NOT_FOUND:
            st.info("施設名を入力してください。")
            return

        # ここから先は収集が要る（EMPTY / NEW）＝ 対象施設とまったく同じ道
        if not st.session_state.get("admin_authed"):
            st.info("この施設の収集にはログイン（管理者）が必要です。")
            return
        _kzkey = _resolve_kaizode_key()
        if not _kzkey:
            st.warning("KAIZODE APIキーが未設定です（管理 → 📡 KAIZODE連携）。")
            return
        _collect_flow(conn, _plan, _kzkey, role="peer")


def _onboard_panel(conn, p, meta: dict) -> None:
    """onboard.plan の判定に従って、次の1手ぶんだけを出す。

    これまでは「候補ボタン → expander を開く → 別の入力欄 → 発注ボタン →
    取り込みボタン → 分析ボタン」と段が多かった。ここでは常に
    **押すべきボタンを1つ**にする。押した先は最後まで自動で進む。
    """
    if p.action == onboard.AMBIGUOUS:
        _html("<div style='height:6px'></div>")
        if p.typed_is_new:
            # 名前が似ているだけで、入力したものはDBに無い。
            # ここで候補しか出さないと、別施設の分析が始まる
            #（「名古屋市美術館」→「デモ美術館」が確定していた）。
            st.caption(f"「{p.query}」はまだ登録されていません。"
                       "名前が近いものがあります。")
        else:
            st.caption("どの施設ですか？")
        for _n in p.candidates:
            if st.button(f"{_n}　·　{meta.get(_n, '')}", key=f"an_sug_{_n}",
                         width="stretch"):
                st.session_state["an_target"] = _n
                st.rerun()
        if p.typed_is_new:
            _html("<div style='height:8px'></div>")
            st.caption("どれでもない場合")
            # 入力した名前そのもので収集に進む。plan をNEW扱いに作り替える。
            _new = onboard.Plan(action=onboard.NEW, query=p.query,
                                facility=p.query, display_name=p.query)
            _collect_flow(conn, _new, _resolve_kaizode_key())
        return

    if p.action == onboard.NOT_FOUND:
        st.info("施設名を入力してください。")
        return

    _html("<div style='height:10px'></div>")

    # 何を分析しようとしているのかを1行で見せる（発注は不可逆なので）
    _sub = p.address or meta.get(p.facility, "")
    _html('<div style="max-width:560px;margin:0 auto;text-align:center;">'
        f'<div style="font-size:17px;font-weight:800;color:#16202B;">'
        f'{escape(p.display_name or p.facility)}</div>'
        + (f'<div style="font-size:13px;color:#8A9098;margin-top:4px;">'
           f'{escape(_sub)}</div>' if _sub else "")
        + "</div>")
    _html("<div style='height:14px'></div>")

    _b1, _b2, _b3 = st.columns([1, 2, 1])
    with _b2:
        if p.action == onboard.READY:
            if st.button(p.label, type="primary", width="stretch",
                         key="an_go_ready"):
                st.session_state["an_target"] = p.facility
                st.rerun()
            return

        # ここから先は収集が要る（EMPTY / NEW）
        _kzkey = _resolve_kaizode_key()
        if not st.session_state.get("admin_authed"):
            st.info("この施設はまだ登録されていません。収集にはログインが必要です。")
            if st.button("🔐 ログインして続ける", width="stretch", key="an_go_login"):
                st.session_state["app_mode"] = "admin"
                st.rerun()
            return
        if not _kzkey:
            st.warning("KAIZODE APIキーが未設定です（管理 → 📡 KAIZODE連携）。")
            return

        _collect_flow(conn, p, _kzkey)


def _candidate_card_html(c, chosen: bool = False) -> str:
    """候補1件ぶんの見出し。件数を主役に置く（選ぶ材料がそれなので）。"""
    _n = f"{c.review_count:,} 件" if c.review_count is not None else "件数不明"
    _r = f"★{c.rating:.1f}" if c.rating is not None else ""
    _bd = "#16202B" if chosen else "#E4E3DD"
    return (
        f'<div style="border:1.5px solid {_bd};border-radius:12px;'
        f'padding:10px 14px;margin:0 0 8px;background:#FFF;text-align:left;">'
        f'<div style="font-size:15px;font-weight:800;color:#16202B;">'
        f'{escape(c.name or "(名称不明)")}</div>'
        f'<div style="font-size:12px;color:#8A9098;margin-top:2px;">'
        f'{escape(c.address or "")}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#16202B;margin-top:6px;">'
        f'口コミ {_n}　{_r}</div></div>'
    )


def _url_flow(conn, p, kzkey: str, link, gmkey: str, role: str = "target") -> None:
    """Google マップの場所URLが貼られたときの確認 → 発注。

    URL は**そのまま**KAIZODE に渡す。こちらで place_id から組み直すと
    `/maps/place/?q=place_id:…` の形になり、KAIZODE が正とする形から外れる。
    Places に聞くのは口コミ数だけで、発注先の URL には触らない。
    """
    if link.short:
        st.warning(
            "短縮URL（maps.app.goo.gl）です。展開しないと施設を確認できません。"
            "マップでその施設を開き、アドレスバーの長いURLを貼ってください。"
        )
        return

    _cands = _gmaps_candidates(link.name, gmkey) if (gmkey and link.name) else []
    _near = _nearest(_cands, link)

    _html(_candidate_card_html(_near, chosen=True) if _near else
          '<div style="border:1.5px solid #E4E3DD;border-radius:12px;padding:10px 14px;'
          'margin:0 0 8px;background:#FFF;text-align:left;">'
          f'<div style="font-size:15px;font-weight:800;color:#16202B;">'
          f'{escape(link.name or p.query)}</div>'
          '<div style="font-size:12px;color:#8A9098;margin-top:4px;">'
          '貼られたURLで発注します</div></div>')

    _name = (_near.name if _near else "") or link.name or p.query
    _pf = precheck.build(
        facility=_name,
        place_id=(_near.place_id if _near else link.place_id),
        review_count=(_near.review_count if _near else None),
        remaining=kaizode.monthly_remaining(conn),
        limit=kaizode.monthly_limit(conn),
        already=onboard._review_count(conn, _name),
    )
    if not link.precise:
        st.caption("⚠️ **URLが施設を1件に指していません** — マップで施設を開いた"
                   "ときの、`/maps/place/…/data=…` を含むURLを貼ってください")
    for _c in _pf.checks:
        _icon = "✅" if _c.ok else ("⛔" if _c.blocking else "⚠️")
        st.caption(f"{_icon} **{_c.label}** — {_c.detail}")
    st.text_input("KAIZODE に渡すURL（貼られたまま）", value=link.url,
                  key="an_url_shown", disabled=True)

    if _pf.blocked:
        st.button("枠が足りません", disabled=True, width="stretch",
                  key=f"an_url_blocked_{role}")
        return
    if st.button(_collect_label(role), type="primary",
                 width="stretch", key=f"an_url_collect_{role}"):
        p.facility = _name
        p.place_id = (_near.place_id if _near else link.place_id) or ""
        _reg = onboard.register(conn, p, ftype=_ftype(role))
        _dsid = _kz_order(conn, kzkey, link.url, _reg)   # ← 貼られたURLをそのまま
        if _dsid:
            data.clear_list_caches()
            st.session_state[f"an_kz_ongoing::{_reg}"] = {
                "dataset_id": _dsid, "facility_name": _reg,
                "auto_analyze": role == "target", "role": role,
            }
            if role == "target":
                st.session_state["an_target"] = _reg
            st.rerun()
    st.caption(_collect_note(role, _pf.remaining))


def _nearest(cands: list, link):
    """貼られたURLの施設に当たる候補。**見つからなければ None**。

    件数を出すために名前で引き直しているだけで、発注先は貼られたURLのまま。
    だから「名前が合う候補が無い」ときに先頭で代用してはいけない。
    代用すると、別の施設の口コミ数を、貼った施設の件数として見せることになる
    （実際それで「グオコタワー」に「国立西洋美術館 8,200件」が付いた）。
    分からないときは分からないままにして、確認項目の側で警告させる。
    """
    if not cands or not link.name:
        return None
    exact = [c for c in cands if (c.name or "").strip() == link.name]
    if exact:
        return exact[0]
    partial = [c for c in cands
               if link.name in (c.name or "") or (c.name or "") in link.name]
    return partial[0] if partial else None


def _kz_probe(conn, kzkey: str, query: str):
    """KAIZODE 側に同じ施設の収集があるか、あるなら何件かを確かめる。

    **1施設につき1回だけ**。件数を聞くのに1件引かれる（count_reviews）ので、
    画面の再描画ごとに聞くと枠が静かに減る。session_state に覚える。

    引かれたぶんは、その場で帳簿に付ける。付け忘れると残枠の表示が
    実態より多くなり、「収まる」と言ってから途中で止まる。
    """
    if not kzkey or not query:
        return None
    ck = f"an_kz_probe::{query}"
    if ck in st.session_state:
        return st.session_state[ck]
    try:
        pr = kaizode.probe_facility(kaizode.KaizodeClient(api_key=kzkey), query)
    except kaizode.KaizodeError as e:
        pr = kaizode.Probe(error=str(e))
    if pr.probe_cost:
        try:
            kaizode.add_monthly_usage(conn, pr.probe_cost)
        except Exception:
            pass
    # 取り直しを頼んだ収集が「進行中」に変わったのを見たら覚えておく。
    # 見ないまま「完了」を読むと、頼んだ直後でまだ動いていないだけかもしれず、
    # 前と同じ件数を「増加 +0 件（確定）」と言ってしまう。
    for d in pr.datasets:
        rec = st.session_state.get(_refresh_key(d.get("dataset_id")))
        if rec is not None and d.get("status") != kaizode.STATUS_DONE:
            rec["seen_running"] = True
    st.session_state[ck] = pr
    return pr


def _refresh_key(dataset_id) -> str:
    return f"an_kz_refresh::{dataset_id}"


def _refresh_state(probe):
    """取り直しの状況。(状態, 前の件数, 今の件数) を返す。頼んでいなければ None。

    状態: "running"（取り直し中）/ "done"（終わって差が確定）/
          "pending"（頼んだがまだ KAIZODE 側の状態が変わっていない）
    """
    if not probe:
        return None
    for d in probe.datasets:
        did = d.get("dataset_id")
        rec = st.session_state.get(_refresh_key(did))
        if rec is None:
            continue
        if d.get("status") != kaizode.STATUS_DONE:
            return ("running", rec.get("before"), None)
        if not rec.get("seen_running"):
            return ("pending", rec.get("before"), None)
        return ("done", rec.get("before"), probe.counts.get(did))
    return None


def _kz_refresh(kzkey: str, query: str, ds: dict, before) -> bool:
    """KAIZODE に同じ収集の取り直しを頼む（新しい収集は作らない）。

    取り直す前の件数を覚えておき、終わったあとの件数との差を「確定」の
    増加として出す。取り込みは差分なので、枠を使うのは増えたぶんだけ。
    """
    did = ds.get("dataset_id") or ""
    try:
        kaizode.KaizodeClient(api_key=kzkey).rerun_dataset(did)
    except kaizode.KaizodeError as e:
        st.error(f"取り直しを依頼できませんでした: {e}")
        return False
    st.session_state[_refresh_key(did)] = {"before": before, "seen_running": False}
    st.session_state.pop(f"an_kz_probe::{query}", None)   # 状態を読み直す
    return True


def _refresh_controls(kzkey: str, query: str, probe, reuse, role: str) -> None:
    """「最新分を取り直す」と「状況を更新」。"""
    state = _refresh_state(probe)
    if state and state[0] in ("running", "pending"):
        if st.button("KAIZODE の状況を更新", width="stretch",
                     key=f"an_kz_reload_{role}"):
            st.session_state.pop(f"an_kz_probe::{query}", None)
            st.rerun()
        return
    if reuse is None or reuse.get("status") != kaizode.STATUS_DONE:
        return
    if state and state[0] == "done":
        return                      # 取り直したばかり
    if st.button("最新分を取り直す（KAIZODE で再収集）", width="stretch",
                 key=f"an_kz_refresh_{role}"):
        before = (probe.counts.get(reuse.get("dataset_id"))
                  if probe else None)
        if _kz_refresh(kzkey, query, reuse, before):
            st.rerun()


def _reusable(probe):
    """発注せずに使える KAIZODE の収集。無ければ None。

    完了済みを優先する（すぐ取り込める）。無ければ進行中のもの
    （新しく発注すると二重になる。完了を待てばよい）。
    """
    if not probe or probe.error:
        return None
    if probe.usable:
        return probe.usable[0]
    # 0 件で完了した収集は使わない。進行中があればそれを待つ。
    running = [d for d in probe.datasets
               if d.get("status") != kaizode.STATUS_DONE]
    return running[0] if running else None


def _go_label(role: str, reuse) -> str:
    """ボタンの文言。**新規発注か、既存の取り込みかを言い分ける。**"""
    if reuse is None:
        return _collect_label(role)
    done = reuse.get("status") == kaizode.STATUS_DONE
    # カードの KAIZODE 行に「既存の収集あり／進行中」と出ているので、
    # ボタンは動作だけを短く言う（細い列で2行に折れないように）。
    # 「取り込んで」だと何を取り込むのか分からない。データの出どころを書く。
    if role == "target":
        return "KAIZODEのデータで分析する" if done else "完了を待って分析する"
    return "KAIZODEのデータで比較に追加" if done else "完了を待って比較に追加"


def _dataset_note(datasets: list) -> str:
    """収集名に、最終更新日と定期取得の有無を添える。

    一覧（GET /datasets）は updated_at と is_scheduled を返す。どれだけ前の
    収集か、KAIZODE が自動で取り直しているかが分かれば、取り直すかどうかを
    決めやすい。updated_at は名前の変更でも動くので「最終更新」と書く
    （「最終収集」とは言わない）。
    """
    d = datasets[0]
    parts = ["／".join(str(x.get("dataset_name") or "") for x in datasets[:2])]
    upd = str(d.get("updated_at") or "")[:10]
    if upd:
        parts.append(f"最終更新 {upd}")
    if d.get("is_scheduled") is True:
        parts.append("定期取得オン")
    elif d.get("is_scheduled") is False:
        parts.append("定期取得オフ")
    return " · ".join(p for p in parts if p)


def _judgement_card(pf, probe, facility: str, address: str = "",
                    google_count=None) -> str:
    """「取れそうか」を1枚にまとめる。

    これまでは「既存の収集」「候補カード」「チェックの箇条書き」と3か所に
    散っていて、枠を使うかどうかを決めるのに目が往復していた。
    """
    def row(label: str, value: str, tone: str = "ink", note: str = "") -> str:
        col = {"ok": "#1B7F4B", "warn": "#B26B00", "ng": "#B3261E",
               "ink": "#16202B"}[tone]
        # 置き場所は細い列（中央寄せの 1/2 幅）。ラベル・値・注記を横に
        # 並べると注記が2行に折れて読めないので、注記は値の下に回す。
        return (
            '<div class="vb-jrow" style="display:flex;gap:10px;'
            'align-items:baseline;padding:6px 0;">'
            '<span style="flex:none;width:72px;font-size:11.5px;color:#8A9098;">'
            f'{escape(label)}</span>'
            '<span style="flex:1;min-width:0;">'
            f'<span style="font-size:14px;font-weight:700;color:{col};">'
            f'{escape(value)}</span>'
            + (f'<span style="display:block;font-size:11.5px;color:#8A9098;'
               f'line-height:1.45;margin-top:1px;">{escape(note)}</span>'
               if note else "")
            + '</span></div>'
        )

    rows = ""

    # ① KAIZODE に既にあるか
    if probe is None:
        rows += row("KAIZODE", "未確認", "ink", "APIキーが未設定です")
    elif probe.error:
        rows += row("KAIZODE", "確認できず", "warn", probe.error[:60])
    elif probe.usable:
        rows += row("KAIZODE", "既存の収集あり", "ok", _dataset_note(probe.usable))
    elif probe.empty_ready and not [d for d in probe.datasets
                                    if d.get("status") != kaizode.STATUS_DONE]:
        # 完了済みだが中身が無い。「あり」と緑で出すと、押せば分析できると
        # 読める。実際は取り込むものが無いので、新しく取得する。
        rows += row("KAIZODE", "既存の収集は0件", "warn",
                    "収集は完了していますが口コミが取れていません。"
                    "新しく取得します")
    elif _refresh_state(probe) is not None:
        # 取り直し中。「収集が進行中」と別行の「再収集中」が二重に出ないよう、
        # ここは既存の収集であることだけ言う（状況は下の「取り直し」行）。
        _names = "／".join(str(d.get("dataset_name") or "") for d in probe.datasets[:2])
        rows += row("KAIZODE", "既存の収集あり（取り直し中）", "warn", _names)
    elif probe.has_existing:
        rows += row("KAIZODE", "収集が進行中", "warn",
                    "完了していないため、件数はまだ確定しません")
    else:
        rows += row("KAIZODE", "新規", "ink", "この施設の収集はまだありません")

    # ② 何件取れそうか。**確定と概算を必ず書き分ける。**
    if pf.expected is None:
        rows += row("取得見込み", "不明", "warn",
                    "件数が読めないため、枠の判定ができません")
    elif pf.exact:
        rows += row("取得見込み", f"{pf.expected:,} 件", "ok",
                    "確定（KAIZODE に問い合わせた実数）")
    else:
        rows += row("取得見込み", f"約 {pf.expected:,} 件", "ink",
                    "概算（Google の口コミ数から）")

    # ②' 取り直すと増えるか。**取り直す前は目安、後は確定**で書き分ける。
    _rs = _refresh_state(probe)
    if _rs and _rs[0] == "running":
        rows += row("取り直し", "KAIZODE で再収集中", "warn",
                    f"取り直す前は {_rs[1]:,} 件。終わったら増えた件数を出します"
                    if _rs[1] is not None else "終わったら増えた件数を出します")
    elif _rs and _rs[0] == "pending":
        rows += row("取り直し", "依頼済み", "warn",
                    "KAIZODE 側の状態がまだ変わっていません。少し待って更新してください")
    elif _rs and _rs[0] == "done" and _rs[1] is not None and _rs[2] is not None:
        _d = _rs[2] - _rs[1]
        rows += row("増えた件数", f"{_d:+,} 件", "ok" if _d > 0 else "ink",
                    f"確定（取り直す前 {_rs[1]:,} 件 → 今 {_rs[2]:,} 件）")
    elif pf.exact:
        _x = precheck.extra_estimate(google_count, pf.expected)
        if precheck.worth_refresh(_x, pf.expected):
            rows += row("追加の見込み", f"約 {_x:,} 件", "warn",
                        "目安（Google の今の件数との差）")

    # ③ 枠
    _q = next((c for c in pf.checks if c.key == "quota"), None)
    if _q is not None:
        _tone = "ok" if _q.ok else ("ng" if _q.blocking else "warn")
        rows += row("今月の残枠", f"{pf.remaining:,} 件", _tone, _q.detail)

    # ④ 人しか判断できないもの（取り違え・二重取得）だけ残す
    for c in pf.checks:
        if c.key in ("quota", "volume") or c.ok:
            continue
        rows += row({"identity": "施設の特定",
                     "duplicate": "すでにある口コミ",
                     "dataset": "二重発注"}.get(c.key, c.label),
                    "要確認", "ng" if c.blocking else "warn", c.detail)

    # 見出しは任意。上で施設名と住所を出している画面では二重になるので省く。
    _head = ""
    if facility:
        _head = (
            f'<div style="font-size:15px;font-weight:800;color:#16202B;">'
            f'{escape(facility)}</div>'
            + (f'<div style="font-size:11.5px;color:#8A9098;margin:1px 0 6px;">'
               f'{escape(address)}</div>' if address else
               '<div style="height:6px"></div>')
        )
    # 行の間の罫線。先頭行の上には引かない（見出しが無いと空の線が浮く）。
    _sep = '<div style="border-top:1px solid #EDEFF3;"></div>'
    rows = rows.replace('<div class="vb-jrow"', _sep + '<div class="vb-jrow"')
    if rows.startswith(_sep):
        rows = rows[len(_sep):]
    if _head:
        rows = _sep + rows
    return (
        '<div style="border:1px solid #E4E3DD;border-radius:12px;'
        'padding:8px 14px 6px;background:#fff;margin:6px 0 10px;">'
        + _head + rows + '</div>'
    )


def _collect_flow(conn, p, kzkey: str, role: str = "target") -> None:
    """施設名 → Google で候補を検索 → 候補を選ぶ → 確認 → 発注。

    以前はボタン1つで「登録 → 発注 → 取り込み → 分析」まで走り切っていた。
    発注は取り消せず、取り込みは月の枠を減らすのに、**何件取るのかを
    誰も見ないまま**始まっていた。3→4 の間に確認を挟む。
    """
    _gmkey = places.get_api_key()
    _pick_key = f"an_pick::{role}::{p.query}"

    # ── URL が貼られた場合 ─────────────────────────────────── #
    #   KAIZODE は「マップで施設を開いたときのURL」を正とする。
    #   貼られたものは**作り直さずそのまま**渡す。件数の確認だけ Places に聞く。
    _link = maps_link.parse(p.query)
    if _link:
        _url_flow(conn, p, kzkey, _link, _gmkey, role)
        return

    # ── STEP 2-3: Google 上の候補 ───────────────────────────── #
    if not _gmkey:
        st.warning(
            "Google Maps APIキーが未設定のため、候補の検索と口コミ数の確認が"
            "できません（管理 → 🔗 連携設定）。名前だけで発注すると、同名の"
            "別施設を拾ったまま枠を使うおそれがあります。"
        )
        _cands = []
    else:
        _cands = _gmaps_candidates(p.query or p.facility, _gmkey)

    _chosen = st.session_state.get(_pick_key)
    if _cands and not _chosen:
        st.caption("この施設で合っていますか？")
        for _i, _c in enumerate(_cands):
            _html(_candidate_card_html(_c))
            if st.button("この施設にする", key=f"an_pick_{role}_{_i}",
                         width="stretch"):
                st.session_state[_pick_key] = _c.place_id
                st.rerun()
        return

    _sel = next((c for c in _cands if c.place_id == _chosen), None)

    # ── STEP 4: 確認 ───────────────────────────────────────── #
    _name = (_sel.name if _sel else "") or p.facility
    _already = onboard._review_count(conn, _name)
    # KAIZODE に既にあるなら、Google からの概算ではなく実数で判定する。
    _probe = _kz_probe(conn, kzkey, _name)
    _pf = precheck.build(
        facility=_name,
        place_id=(_sel.place_id if _sel else p.place_id),
        review_count=(_sel.review_count if _sel else None),
        remaining=kaizode.monthly_remaining(conn),
        limit=kaizode.monthly_limit(conn),
        already=_already,
        # 既存の収集は**再利用する**ので、二重発注の警告は出さない。
        known_count=(_probe.known_count if _probe else None),
    )
    _reuse = _reusable(_probe)

    # 施設名と住所はこの上（プランの見出し）に出ているので、カードでは省く。
    _html(_judgement_card(_pf, _probe, "",
                          google_count=(_sel.review_count if _sel else None)))

    _b_back, _b_go = st.columns([1, 2])
    with _b_back:
        if st.button("選び直す", key=f"an_pick_back_{role}", width="stretch"):
            st.session_state.pop(_pick_key, None)
            st.rerun()
    with _b_go:
        if _pf.blocked:
            st.button("枠が足りません", disabled=True, width="stretch",
                      key=f"an_go_blocked_{role}")
        elif st.button(_go_label(role, _reuse), type="primary",
                       width="stretch", key=f"an_go_collect_{role}"):
            if _sel:
                p.place_id = _sel.place_id
                p.facility = _name
                p.maps_url = _sel.maps_url
            _reg = onboard.register(conn, p, ftype=_ftype(role))
            # KAIZODE に既にあるなら**発注しない**。その収集を追いかけるだけ。
            #   完了済みなら追跡がすぐ完了を見て取り込み → 分析へ進む。
            _dsid = (_reuse.get("dataset_id") if _reuse
                     else _kz_order(conn, kzkey, onboard.collect_url(p), _reg))
            if _dsid:
                data.clear_list_caches()
                st.session_state.pop(_pick_key, None)
                # ここから先は自動: 収集を待つ → 取り込む → 分析（または比較施設へ追加）
                st.session_state[f"an_kz_ongoing::{_reg}"] = {
                    "dataset_id": _dsid, "facility_name": _reg,
                    "auto_analyze": role == "target", "role": role,
                }
                if role == "target":
                    st.session_state["an_target"] = _reg
                st.rerun()
    _refresh_controls(kzkey, _name, _probe, _reuse, role)
    if _reuse is not None and not _pf.blocked:
        # 収集の照合は名前の部分一致なので、別の施設を拾っている可能性がある。
        # カードに名前を出したうえで、違うときの逃げ道を残す。
        if st.button("別の施設なので新しく取得する", width="stretch",
                     key=f"an_go_fresh_{role}"):
            if _sel:
                p.place_id = _sel.place_id
                p.facility = _name
                p.maps_url = _sel.maps_url
            _reg = onboard.register(conn, p, ftype=_ftype(role))
            _dsid = _kz_order(conn, kzkey, onboard.collect_url(p), _reg)
            if _dsid:
                data.clear_list_caches()
                st.session_state.pop(_pick_key, None)
                st.session_state[f"an_kz_ongoing::{_reg}"] = {
                    "dataset_id": _dsid, "facility_name": _reg,
                    "auto_analyze": role == "target", "role": role,
                }
                if role == "target":
                    st.session_state["an_target"] = _reg
                st.rerun()
    st.caption(_collect_note(role, _pf.remaining, _reuse))


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
# 解析中（running）画面のCSS。ブラウザでの実測テストからも参照するので
# モジュール定数にしてある（テストが本物の文字列を見ないと意味がない）。
#
# CANCEL_ZONE_Z はローディングのオーバーレイ
# （components.loading_card_html の z-index:2147483000）より大きいこと。
# 小さいとボタンが板の下に入って物理的に押せない。
CANCEL_ZONE_Z = 2147483100

_RUNNING_CSS = (
    "<style>[data-testid='stHeader']{display:none!important;}"
    "[data-testid='stStatusWidget']{display:none!important;}"
    "[data-testid='stToolbar']{display:none!important;}"
    "[data-testid='stAppViewContainer']{opacity:1!important;}"
    ".st-key-an_cancel_zone{position:fixed!important;left:50%;"
    "transform:translateX(-50%);bottom:26px;width:min(360px,84vw);"
    f"z-index:{CANCEL_ZONE_Z}!important;text-align:center;}}"
    "</style>"
)


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
    """Places の写真と住所をセッション内で一時的に持つ。

    Streamlit は操作のたびにスクリプト全体を再実行するので、素で呼ぶと
    ボタンひとつで6施設ぶんの API 呼び出しが飛ぶ。写真も住所も短時間（30分）
    だけ持つ性能目的の一時キャッシュ（DBには焼かない＝規約どおり都度取得）。

    住所は写真と同じ Details 呼び出しに相乗りさせている（photos を要求した
    時点で Pro 階層なので、住所を足しても課金は変わらない）。

    写真は **data: URI（実体）** で返す。以前は `key=...` 付きの Google 媒体URL
    をそのまま返して <img src> に置いていたが、分析画面はログイン不要なので
    ページのソースからAPIキーが読めてしまっていた。実体をサーバ側で取れば
    キーは外に出ない。ブラウザが毎回 Google を叩かなくなるぶん呼び出しも減る。
    """
    from src import places  # noqa: PLC0415

    conn = db.get_conn(config.DB_PATH)
    d = places.details_for_facility(conn, name, api_key)
    uri = (places.fetch_photo_data_uri(d.photo.name, api_key)
           if d.photo else "")
    return {
        "data_uri": uri,
        "attribution": d.photo.attribution if (d.photo and uri) else "",
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
    if not bundle.get("photo_data_uri") and got.get("data_uri"):
        bundle["photo_data_uri"] = got["data_uri"]
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
        if pg.get("data_uri"):
            peer["photo_data_uri"] = pg["data_uri"]
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

        # 較正はここで**1回だけ**行い、PPTX と画面スライドに同じ行列を渡す。
        #
        # 以前は build_bundle の中でしか較正しておらず、その手前で呼ばれる
        # build_report には素点が渡っていた。同じ分析なのに画面が「3.85/5」、
        # 客先に出る PPTX が「66/100」(=3.30/5) と食い違っていた。
        # 較正の基準は母集団全体（比較モードで絞る前）にすること。
        # calibrate_matrix は冪等なので、build_bundle 側が再度呼んでも
        # 二重には掛からない。
        if config.SCORE_CALIBRATION:
            matrix, _ = topic_score.calibrate_matrix(matrix)

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

        # ── 18枚固定版（原典 ppt-spec-v5）も併せて出す ──────────────── #
        #    追加の LLM 呼び出しは無い。ここまでで計算済みのものを詰め直すだけ。
        #    既存の可変長レポートは残し、選べるようにする。
        _tmp_v5 = None
        try:
            from src import nmsi as _nmsi_pkg  # noqa: PLC0415
            from src.nmsi import run as _nmsi_run  # noqa: PLC0415
            _nmsi_res = _nmsi_run.get_result(tconn, tgt)
        except Exception:
            _nmsi_res = None
        try:
            _rev_pairs = [(r[0], r[1]) for r in tconn.execute(
                "SELECT rating, text FROM review WHERE facility_id = "
                "(SELECT id FROM facility WHERE name = ?) "
                "AND text IS NOT NULL AND TRIM(text) != ''", (tgt,)).fetchall()]
            _ctx5 = report_v5.Ctx(
                target=tgt, conn=tconn, comp=_comp2, profile=_profile,
                topic_score=_ts_result if not _ts_result.empty else None,
                insights=_insights, nmsi=_nmsi_res,
                vffi=vffi.assess(_rev_pairs), reviews=_rev_pairs,
                rares=rare.extract([t for _r, t in _rev_pairs], tgt),
                baseline_label=(_comp2.baseline_label if _comp2 else "（比較データなし）"),
            )
            _tmp_v5 = Path(tempfile.mkdtemp()) / f"VoiceBAUM_18p_{tgt}.pptx"
            report_v5.build_report_v5(_ctx5, _tmp_v5)
        except Exception:
            _tmp_v5 = None      # 18枚版が作れなくても既存レポートは出す

        # 結果を受け渡し用 dict へ（session_state 反映はメインスレッド）
        ss_out["an_preview"]        = _bundle
        ss_out["an_result_path"]    = str(_tmp)
        ss_out["an_result_path_v5"] = str(_tmp_v5) if _tmp_v5 else None
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

    # ── 口コミがまだ1件も無いとき ─────────────────────────────────────── #
    #   **検索窓は必ず出す。** 以前はここで st.stop() していたため、
    #   空のDBだと施設名を打ち込む欄すら出ず、「管理からCSVを入れてくれ」で
    #   行き止まりになっていた。施設名を入れれば Google と KAIZODE から
    #   取りに行けるのだから、CSV は入口ではなく一手段にすぎない。
    #   _names が空でも onboard.plan() は NEW に落ちるので、そのまま進める。

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
        _html("""
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
        """)

        _meta = _facility_meta()
        _sp, _mid, _sp2 = st.columns([1, 2.4, 1])
        with _mid:
            _html("<div style='height:8vh'></div>")
            _html('<div class="vb-hero-title">VoiceBAUM</div>')
            _html('<p class="vb-hero-sub">オープン後の来場者評価（口コミ）を活用した実態分析ツール</p>')
            _html("<div style='height:30px'></div>")

            _target = st.session_state.get("an_target")

            if not _target:
                # ── 空の状態：施設名を1回入れるだけ ──────────────────── #
                #   入力から「次に何をすべきか」を onboard.plan が1つに決める。
                #   画面には、その1手ぶんのボタンだけを出す。
                _q = st.text_input(
                    "施設名を入力",
                    placeholder="施設名、または Google マップのURL（Enterで検索）",
                    key="an_search", label_visibility="collapsed",
                )
                _qs = _q.strip()
                if _qs:
                    _plan = onboard.plan(
                        conn, _qs, names=_names, gmaps_key=places.get_api_key())
                    _onboard_panel(conn, _plan, _meta)
                else:
                    _html('<div style="max-width:440px;margin:24px auto 0;'
                        'text-align:center;background:#E4E3DD;color:#A7ABB0;'
                        'font-weight:700;font-size:15px;padding:16px;'
                        'border-radius:12px;">この内容で分析する</div>')

            else:
                # ── 選択済み：施設カード + 分析タイプ選択 + 実行ボタン ── #
                _chk = db.facility_stats(conn, _target)
                _stats_ok = bool(_chk and _chk["n_reviews"] > 0)
                _others = [n for n in _names if n != _target]

                _html(_selected_card_html(_target, _meta))
                _html("<div style='height:20px'></div>")

                # 口コミがまだ無い間は、比較の方式・比較施設・レポート構成を出さない。
                # どれも口コミが入るまで決めようがなく、収集の状況が埋もれる
                # （2026-11-26「情報量多すぎて煩雑」）。取り込めたら自動で出る。
                _run_block = ""
                if _stats_ok:
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

                    _html("<div style='height:8px'></div>")

                    # 「指定競合」を選んだのに1件も選ばないまま実行すると、
                    # 警告なく市場全体比較のスライドが出る（順位も基準値もDB全施設）。
                    # 「競合と比べた資料」のつもりで作ったものを、そうでないまま
                    # 外に出してしまうので、実行を止めて選ばせる。
                    _run_block = ""

                    if _an_type == "competitor":
                        if _others:
                            # 既定値は置かない。facility.type は target/comparison の
                            # 2値しかなく「どの施設の競合か」を持つ列が無い。しかも
                            # KAIZODE 同期で入る施設は全部 comparison になるので、
                            # facilities_by_type(conn,"comparison")[:5] は
                            # 「名前順で先頭5件」でしかない。それを競合として黙って
                            # 採用した資料が出るほうが害が大きい。
                            # （v0.53.0 以前は既定を書いていたが、app.py が
                            #   an_peers に [] を必ず入れるため一度も効いていなかった）
                            _prev_sel = [p for p in
                                         st.session_state.get("an_peers") or []
                                         if p in _others][:5]
                            _selected_peers = st.multiselect(
                                "比較施設を選択（最大5件）",
                                options=_others,
                                default=_prev_sel,
                                max_selections=5,
                                key=peer_widget_key(),
                                placeholder="施設名を入力して絞り込む...",
                            )
                            st.session_state["an_peers"] = _selected_peers
                            st.session_state["an_mode"] = "compare" if _selected_peers else "single"
                            st.session_state["an_axis_label"] = "比較施設の平均"
                            _peer_add_panel(conn, _names, _target, _selected_peers)
                            if not _selected_peers:
                                _run_block = (
                                    "比較する施設を1件以上選んでください。"
                                    "選ばずに進めると、指定競合ではなく**市場全体**"
                                    "との比較になります（それでよければ"
                                    "「📊 マーケット比較」を選んでください）。"
                                )
                        else:
                            st.info(
                                "DBに比較できる施設がまだありません。"
                                "下から探して追加できます。"
                            )
                            st.session_state["an_mode"] = "single"
                            st.session_state["an_peers"] = []
                            _peer_add_panel(conn, _names, _target, [])
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
                    _html("<div style='height:10px'></div>")
                    _dc1, _dc2, _dc3 = st.columns([1, 2, 1])
                    with _dc2:
                        st.toggle(
                            "「詳細」ページも作る",
                            value=st.session_state.get("an_with_detail", True),
                            key="an_with_detail",
                            help="市場内ポジション（詳細）／指定競合との比較（詳細）／"
                                 "空間体験分析（詳細）の3枚。オフにすると7枚構成になります。",
                        )
                        # NMSI が計算済みならレポートは1枚増える。押す前に
                        # 見える枚数と実際が食い違わないようにする。
                        _n_slides = len(slides.report_slides(
                            detail=st.session_state.get("an_with_detail", True)))
                        try:
                            from src.nmsi import run as _nmsi_run  # noqa: PLC0415
                            if _nmsi_run.get_result(conn, _target):
                                _n_slides += 1
                        except Exception:
                            pass
                        st.caption(f"レポートは全 {_n_slides} 枚（＋冒頭の免責）になります")

                # ── 実行ボタン ────────────────────────────────────────── #
                _html("<div style='height:14px'></div>")
                _rc1, _rc2, _rc3 = st.columns([1, 2, 1])
                with _rc2:
                    if _stats_ok:
                        if _run_block:
                            st.info(_run_block)
                        if st.button("この内容で分析する", type="primary",
                                     width="stretch", key="an_run",
                                     disabled=bool(_run_block)):
                            st.session_state["an_screen"] = "running"
                            st.rerun()
                    else:
                        # 収集中は進捗カードが状況を言うので、警告を重ねない。
                        if not st.session_state.get(f"an_kz_ongoing::{_target}"):
                            st.caption("この施設の口コミはまだありません。"
                                       "下の判定を見て、取得してから分析します。")
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
        #
        # 中止ボタンだけはオーバーレイより前に出す。ローディングは
        # components.loading_card_html() が position:fixed / inset:0 /
        # z-index:2147483000 の不透明な板を全面に敷くので、素直に描くと
        # ボタンはその**下**に入って物理的に押せない（v0.44.0 で足してから
        # ずっと押せていなかった）。
        _html(_RUNNING_CSS)

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
                _html(_loading_card_html(
                        _p.get("step", 2), _p.get("detail", ""),
                        server_secs=(time.time() - _started) if _started else None,
                    ))

            _progress_ui()

            # 止まったときに待つしかない状態にしない。押せば設定画面へ戻れる。
            # ワーカーには cancelled を立てて、次のチェックポイントで手を引かせる。
            #
            # キー付きコンテナにするのは、上の CSS（.st-key-an_cancel_zone）で
            # オーバーレイより手前に浮かせるため。ボタンと注記を1つの箱に
            # 入れておかないと、注記だけがオーバーレイの下に残る。
            with st.container(key="an_cancel_zone"):
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
        _html(
            _loading_card_html(0, f"「{_target}」の口コミ {_n_rev:,} 件をDBから読み込んでいます"),
            into=_ph0,
        )
        _rev_rows = conn.execute(
            "SELECT rating, text FROM review WHERE facility_id = ?", (_fid,)
        ).fetchall()
        _revs = [(_r["rating"], _r["text"] or "") for _r in _rev_rows]
        _n_with_text = sum(1 for _, t in _revs if t.strip())

        _html(
            _loading_card_html(1, f"口コミ {_n_rev:,} 件 ／ 本文あり {_n_with_text:,} 件 — 評点・ポジ率を集計中"),
            into=_ph0,
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
        #    PowerPoint は2種類出る。既定（可変長・この画面と同じ構成）と、
        #    18枚固定版（原典 ppt-spec-v5）。後者はデータが無い面も必ず作る。
        _PPTX_MIME = ("application/vnd.openxmlformats-officedocument"
                      ".presentationml.presentation")
        _path_v5 = st.session_state.get("an_result_path_v5")
        _has_v5 = bool(_path_v5 and Path(_path_v5).exists())
        _hc1, _hc2, _hc3 = st.columns([1, 1, 1] if _has_v5 else [1, 1, 0.001])
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
                        mime=_PPTX_MIME,
                        type="primary",
                        width="stretch",
                        key="an_dl",
                    )
            else:
                st.error("レポートファイルが見つかりません。設定に戻って再実行してください。")
        with _hc3:
            if _has_v5:
                with open(_path_v5, "rb") as _f5:
                    st.download_button(
                        "⬇ 18枚固定版",
                        data=_f5.read(),
                        file_name=Path(_path_v5).name,
                        mime=_PPTX_MIME,
                        width="stretch",
                        key="an_dl_v5",
                        help="原典 ppt-spec-v5 の18枚構成。データが無い面も"
                             "「データ不足」と明記して必ず作ります。",
                    )

        _html("<div style='height:8px'></div>")

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

            _html(slides.slide0_disclaimer(_bundle))

            # ── PROFILE：この場でインライン編集（写真アップ＋各項目の手入力）──── #
            #    ここは分析画面（ログイン不要）の中だが、中の3つのボタンは
            #    db.save_photo / db.upsert_facility / db.delete_photo を叩く
            #    ＝本番DBへの書き込み。URLを知っている人なら誰でも施設写真を
            #    消せる状態だったので、編集は管理ログイン必須にする。
            #    _ekey はセッションに残るので、入口だけでなくパネル本体も見る
            #    （編集中にログアウトした場合に開いたままにしない）。
            _can_edit = bool(st.session_state.get("admin_authed"))
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

            if _can_edit and st.session_state.get(_ekey):
                with st.container(border=True):
                    _html('<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">'
                        f'<span style="font-size:11px;font-weight:800;letter-spacing:.06em;color:#fff;'
                        f'background:{ACCENT};padding:4px 10px;border-radius:6px;">PROFILE 編集</span>'
                        '<span style="font-size:15px;font-weight:800;color:#16202B;">写真アップロードと情報の書き込み</span></div>')
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
                            _html('<div style="aspect-ratio:1;border-radius:12px;background:#F1F0EA;'
                                'display:flex;align-items:center;justify-content:center;color:#A7ABB0;">施設写真</div>')
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
                _html(slides.slide1_facility_info(_bundle))
                _pe1, _pe2, _pe3 = st.columns([1, 1.4, 1])
                with _pe2:
                    if _can_edit:
                        if st.button("✏️ PROFILEを編集（写真・住所など）", width="stretch",
                                     key=f"prof_edit_btn_{_target}"):
                            st.session_state[_ekey] = True
                            st.rerun()
                    else:
                        # 閲覧者にはボタン自体を出さない。運用者が未ログインの
                        # ときだけ迷わないように入口を示す（159行と同じ形）。
                        if st.button("🔐 ログインして PROFILE を編集",
                                     width="stretch",
                                     key=f"prof_edit_login_{_target}"):
                            st.session_state["app_mode"] = "admin"
                            st.rerun()

            # ── 分析レポート本体（PDF「20260726_VoiceBAUM_v1」p3〜p12 準拠）──── #
            #    SLIDE 1 は上の PROFILE 編集ブロック側で描いている（編集中は
            #    フォームに差し替わるため）。ここは SLIDE 2 以降。
            #    deck() は固定の枚に続けて、データが揃っている分だけ足す
            #    （NMSI は計算済みのときだけ増える）。
            for _slide_html in slides.deck(
                _bundle, detail=st.session_state.get("an_with_detail", True)
            )[1:]:                       # SLIDE 1 は上の PROFILE ブロックで描画済み
                _html(_slide_html)
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
