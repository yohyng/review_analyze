"""VoiceBaum — 口コミ分析アプリ v0.5.0

Analysis mode: select facility → single/compare → analyze → PPTX download
Admin mode:    dashboard / facilities / data import / detailed analysis / settings
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
    analysis,
    auth,
    charts,
    config,
    csv_profiler,
    db,
    geocode,
    images,
    kaizode,
    llm,
    preview,
    report,
    review_csv,
    score_excel,
    scoring,
    search,
    text_analysis,
    topic_score,
    topics,
)

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="VoiceBaum",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Design tokens + global CSS
# ─────────────────────────────────────────────────────────────────────────────
# Design tokens + global CSS live in src/ui/theme.py
from src.ui import theme
from src.ui.theme import ACCENT, ACCENT_SOFT, ACCENT_RING

theme.inject_global_css()


# ─────────────────────────────────────────────────────────────────────────────
# DB connection
# ─────────────────────────────────────────────────────────────────────────────
from src.ui import admin_mode, analysis_mode, components, data

conn = data.get_conn()


# ─────────────────────────────────────────────────────────────────────────────
# Session state defaults
# ─────────────────────────────────────────────────────────────────────────────
for _k, _v in {
    "app_mode": "analysis",
    "an_screen": "setup",
    "an_target": None,
    "an_mode": "single",
    "an_peers": [],
    "an_result_path": None,
    "an_topic_list": [],
    "an_topic_score": None,
    "admin_page": "dashboard",
    "admin_email": None,
    "analysis_target": None,
    "insights": None,
    "insights_facility": None,
    "selected_facility": None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


_is_an = st.session_state["app_mode"] == "analysis"


# ─────────────────────────────────────────────────────────────────────────────
# Navigation — top header (analysis mode) OR left sidebar (admin mode)
# ─────────────────────────────────────────────────────────────────────────────
if _is_an:
    # Hide the sidebar entirely so the analysis screen matches the hero design.
    st.markdown(
        "<style>[data-testid='stSidebar']{display:none!important;}"
        "[data-testid='collapsedControl']{display:none!important;}</style>",
        unsafe_allow_html=True,
    )
    # Header is hidden during the analysis run so the loading overlay stands alone.
    if st.session_state["an_screen"] != "running":
        _hc1, _hc2 = st.columns([2.3, 1])
        with _hc1:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:11px;padding:2px 0 6px;">
              <div style="width:38px;height:38px;border-radius:11px;background:{ACCENT};
                          display:flex;align-items:center;justify-content:center;
                          color:#fff;font-weight:800;font-size:17px;flex:none;">V</div>
              <div style="line-height:1.2;">
                <div style="font-weight:800;font-size:18px;color:#16202B;letter-spacing:-.01em;">VoiceBAUM</div>
                <div style="font-size:11.5px;color:#8A9098;">口コミから、施設の実力を可視化する</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        with _hc2:
            _tt1, _tt2, _tt3 = st.columns([1, 1, 0.7])
            with _tt1:
                st.button("分析", type="primary", use_container_width=True, key="hdr_an")
            with _tt2:
                if st.button("管理", type="secondary", use_container_width=True, key="hdr_adm"):
                    st.session_state["app_mode"] = "admin"
                    st.rerun()
            with _tt3:
                if st.button("EN", type="secondary", use_container_width=True, key="hdr_en"):
                    st.toast("英語表示は今後対応予定です。", icon="🌐")
        st.markdown("<hr style='margin:6px 0 4px;'>", unsafe_allow_html=True)

else:
    # ── 管理モードはログイン必須（メール＋パスワードのアカウント制）── #
    #   ・新規登録は招待コード SIGNUP_CODE を知っている人だけ（登録ゲート）
    #   ・ADMIN_PASSWORD は「最初の1人を作る/ロックアウト回避」用の非常口
    if not st.session_state.get("admin_authed"):
        try:
            _n_users = auth.count_users(conn)
        except Exception:
            _n_users = 0
        _has_signup = bool(auth.signup_code())
        _has_master = bool(auth.admin_password())
        # 入口が一つも無い（登録もできない・非常口も無い・既存ユーザーも無い）ときだけロック
        _locked = (_n_users == 0 and not _has_signup and not _has_master)

        st.markdown(
            "<style>[data-testid='stSidebar']{display:none!important;}"
            "[data-testid='collapsedControl']{display:none!important;}</style>",
            unsafe_allow_html=True,
        )
        _sp1, _mid, _sp2 = st.columns([1, 1.1, 1])
        with _mid:
            st.markdown("<div style='height:9vh'></div>", unsafe_allow_html=True)
            st.markdown(f"""
            <div style="text-align:center;margin-bottom:14px;">
              <div style="width:52px;height:52px;border-radius:14px;background:{ACCENT};
                          display:inline-flex;align-items:center;justify-content:center;
                          color:#fff;font-weight:800;font-size:22px;">V</div>
              <div style="font-weight:800;font-size:20px;color:#16202B;margin-top:10px;">管理コンソール</div>
              <div style="font-size:12.5px;color:#8A9098;margin-top:4px;">
                管理モードへのアクセスにはログインが必要です</div>
            </div>
            """, unsafe_allow_html=True)

            if _locked:
                st.warning("管理画面はロックされています。招待コード（SIGNUP_CODE）を設定すると"
                           "アカウント登録できるようになります。")
                st.code(
                    '# .streamlit/secrets.toml（Streamlit Cloud は Settings > Secrets）\n'
                    'SIGNUP_CODE    = "登録に必要な招待コード（合言葉）"\n'
                    'ADMIN_PASSWORD = "任意: 非常口のマスターパスワード"',
                    language="toml",
                )
            else:
                _tab_login, _tab_reg = st.tabs(["ログイン", "新規登録"])

                # ── ログイン ────────────────────────────────────────────── #
                with _tab_login:
                    with st.form("admin_login"):
                        _em_in = st.text_input("メールアドレス", key="adm_login_email")
                        _pw_in = st.text_input("パスワード", type="password", key="adm_login_pw")
                        _login = st.form_submit_button(
                            "🔐 ログイン", type="primary", use_container_width=True
                        )
                    if _login:
                        _user = None
                        try:
                            _user = auth.authenticate(conn, _em_in, _pw_in)
                        except Exception:
                            _user = None
                        if _user:
                            st.session_state["admin_authed"] = True
                            st.session_state["admin_email"] = _user["email"]
                            st.rerun()
                        elif auth.check_admin_password(_pw_in):
                            # 非常口（マスターパスワード）: メール欄は任意
                            st.session_state["admin_authed"] = True
                            st.session_state["admin_email"] = (
                                auth.normalize_email(_em_in) or "master"
                            )
                            st.rerun()
                        else:
                            time.sleep(1)   # 総当たり抑止
                            st.error("メールアドレスまたはパスワードが違います。")

                # ── 新規登録（招待コード必須）───────────────────────────── #
                with _tab_reg:
                    if not _has_signup:
                        st.info("新規登録は現在無効です。管理者が招待コード（SIGNUP_CODE）を"
                                "設定すると有効になります。")
                        st.code('SIGNUP_CODE = "登録に必要な招待コード"', language="toml")
                    else:
                        with st.form("admin_register"):
                            _rem = st.text_input("メールアドレス", key="adm_reg_email")
                            _rpw = st.text_input("パスワード（8文字以上）", type="password",
                                                 key="adm_reg_pw")
                            _rpw2 = st.text_input("パスワード（確認）", type="password",
                                                  key="adm_reg_pw2")
                            _code = st.text_input("招待コード", type="password",
                                                  key="adm_reg_code",
                                                  help="管理者から共有された合言葉を入力")
                            _reg = st.form_submit_button(
                                "✳️ アカウント作成", type="primary", use_container_width=True
                            )
                        if _reg:
                            if not auth.check_signup_code(_code):
                                time.sleep(1)
                                st.error("招待コードが違います。")
                            elif _rpw != _rpw2:
                                st.error("パスワード（確認）が一致しません。")
                            else:
                                try:
                                    _u = auth.create_user(conn, _rem, _rpw)
                                    st.session_state["admin_authed"] = True
                                    st.session_state["admin_email"] = _u["email"]
                                    st.rerun()
                                except auth.AuthError as _e:
                                    st.error(str(_e))
                                except Exception as _e:
                                    st.error(f"登録に失敗しました: {_e}")

            if st.button("← 分析モードに戻る", use_container_width=True, key="adm_back"):
                st.session_state["app_mode"] = "analysis"
                st.rerun()
        st.stop()

    with st.sidebar:
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;padding:14px 4px 14px;">
          <div style="width:34px;height:34px;border-radius:9px;background:{ACCENT};
                      display:flex;align-items:center;justify-content:center;
                      color:#fff;font-weight:800;font-size:15px;flex:none;">V</div>
          <div style="line-height:1.2;">
            <div style="font-weight:800;font-size:16px;color:#16202B;letter-spacing:-.01em;">VoiceBAUM</div>
            <div style="font-size:11px;color:#8A9098;">管理コンソール</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        _c1, _c2 = st.columns(2)
        with _c1:
            if st.button("📊 分析", use_container_width=True, type="secondary", key="mode_an"):
                st.session_state["app_mode"] = "analysis"
                st.rerun()
        with _c2:
            st.button("⚙️ 管理", use_container_width=True, type="primary", key="mode_adm")

        st.markdown("<hr>", unsafe_allow_html=True)

        _page = st.session_state["admin_page"]
        _NAV = [
            ("📊 ダッシュボード", "dashboard"),
            ("🏢 施設管理", "facilities"),
            ("📥 データ取り込み", "import"),
            None,
            ("🧭 トピックスコア", "topic"),
            ("📈 強み・弱み", "score"),
            ("💬 テキスト分析", "text"),
            ("📑 レポート出力", "report"),
            None,
            ("🔬 CSVプロファイラ", "profiler"),
            ("📡 KAIZODE連携", "kaizode"),
            ("🔗 連携設定", "integration"),
            ("👤 アカウント", "account"),
        ]
        for _item in _NAV:
            if _item is None:
                st.markdown(
                    "<div style='font-size:10.5px;font-weight:700;color:#A7ABB0;"
                    "letter-spacing:.08em;padding:8px 0 2px;'>──────────────</div>",
                    unsafe_allow_html=True,
                )
            else:
                _lbl, _key = _item
                if st.button(
                    _lbl, key=f"nav_{_key}", use_container_width=True,
                    type="primary" if _page == _key else "secondary",
                ):
                    st.session_state["admin_page"] = _key
                    st.rerun()

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        _who = st.session_state.get("admin_email")
        if _who:
            st.markdown(
                f"<div style='font-size:11px;color:#8A9098;padding:0 4px 4px;'>"
                f"ログイン中: <b style='color:#16202B;'>{escape(str(_who))}</b></div>",
                unsafe_allow_html=True,
            )
        if st.button("🔓 ログアウト", key="adm_logout", use_container_width=True):
            st.session_state["admin_authed"] = False
            st.session_state["admin_email"] = None
            st.session_state["app_mode"] = "analysis"
            st.rerun()

        st.markdown(
            f"<div style='padding:20px 4px 4px;font-size:11px;color:#C5C4BC;'>v{config.APP_VERSION}</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
# UI helpers moved to src/ui/data.py (data/cache) and src/ui/components.py
# (presentational). Aliased so the page code below reads unchanged.
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


# ─────────────────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS MODE
# ═════════════════════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state["app_mode"] == "analysis":
    analysis_mode.render()


# ─────────────────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
# ADMIN MODE
# ═════════════════════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────────────
else:
    admin_mode.render()
