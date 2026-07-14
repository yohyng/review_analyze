"""VoiceBaum — 口コミ分析アプリ v0.5.0

Analysis mode: select facility → single/compare → analyze → PPTX download
Admin mode:    dashboard / facilities / data import / detailed analysis / settings
"""
from __future__ import annotations

import base64
import io
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
ACCENT = "#B0338A"
ACCENT_SOFT = "rgba(176,51,138,0.09)"
ACCENT_RING = "rgba(176,51,138,0.22)"

st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] {{
  font-family: 'Manrope', 'Noto Sans JP', system-ui, sans-serif !important;
  -webkit-font-smoothing: antialiased;
}}
.stApp, [data-testid="stAppViewContainer"] {{
  background-color: #F7F7F4 !important;
}}
[data-testid="stSidebar"] {{
  background-color: #FFFFFF !important;
  border-right: 1px solid #E9E8E2 !important;
}}
/* Metrics */
[data-testid="metric-container"] {{
  background: #fff;
  border: 1px solid #E9E8E2;
  border-radius: 14px;
  padding: 18px 20px !important;
  box-shadow: 0 1px 2px rgba(20,30,40,.04), 0 6px 20px rgba(20,30,40,.04);
}}
[data-testid="metric-container"] > label {{
  color: #8A9098 !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  letter-spacing: .03em;
}}
[data-testid="metric-container"] [data-testid="stMetricValue"] {{
  color: #16202B !important;
  font-weight: 800 !important;
}}
/* Primary button */
.stButton > button[kind="primary"] {{
  background: {ACCENT} !important;
  border: none !important;
  border-radius: 11px !important;
  font-weight: 700 !important;
  box-shadow: 0 8px 18px rgba(20,30,40,.14) !important;
}}
.stButton > button[kind="primary"]:hover {{
  filter: brightness(1.08) !important;
}}
.stButton > button[kind="secondary"] {{
  border-color: #E4E3DD !important;
  border-radius: 10px !important;
  color: #16202B !important;
}}
.stButton > button[kind="secondary"]:hover {{
  border-color: #16202B !important;
}}
/* Download button */
.stDownloadButton > button {{
  background: {ACCENT} !important;
  color: #fff !important;
  border: none !important;
  border-radius: 11px !important;
  font-weight: 700 !important;
  box-shadow: 0 8px 18px rgba(20,30,40,.14) !important;
}}
.stDownloadButton > button:hover {{ filter: brightness(1.08) !important; }}
/* Inputs */
.stTextInput input, .stTextArea textarea {{
  border-radius: 10px !important;
  border-color: #E4E3DD !important;
}}
/* Tabs */
[data-testid="stTabs"] [role="tablist"] {{
  background: #F1F0EA;
  border-radius: 10px;
  padding: 3px;
  gap: 3px;
  border: none !important;
  border-bottom: none !important;
}}
[data-testid="stTabs"] [role="tab"] {{
  border-radius: 8px !important;
  font-weight: 600 !important;
  color: #5B6672 !important;
  border: none !important;
  background: transparent !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
  background: #fff !important;
  color: #16202B !important;
  box-shadow: 0 1px 4px rgba(20,30,40,.10) !important;
}}
[data-testid="stTabs"] [role="tabpanel"] {{
  padding-top: 16px !important;
}}
/* Expanders */
[data-testid="stExpander"] {{
  border: 1px solid #E9E8E2 !important;
  border-radius: 12px !important;
  background: #fff !important;
}}
/* Divider */
hr {{ border-color: #E9E8E2 !important; margin: 18px 0 !important; }}
/* Alert boxes */
[data-testid="stAlert"] {{ border-radius: 10px !important; }}
/* Dataframes */
[data-testid="stDataFrame"] {{
  border-radius: 12px !important;
  overflow: hidden !important;
  border: 1px solid #E9E8E2 !important;
}}
/* Utility */
.vb-step {{
  font-size: 11.5px; font-weight: 700; letter-spacing: .12em;
  color: {ACCENT}; margin-bottom: 6px; text-transform: uppercase;
}}
.vb-h1 {{
  font-size: clamp(22px, 3vw, 30px); font-weight: 800;
  letter-spacing: -.02em; color: #16202B; margin: 0 0 8px; line-height: 1.2;
}}
.vb-sub {{
  font-size: 15px; color: #5B6672; margin: 0; line-height: 1.6;
}}
/* Hero (analysis setup) */
.vb-hero-title {{
  font-size: clamp(46px, 8vw, 88px); font-weight: 800; letter-spacing: -.03em;
  color: #16202B; text-align: center; margin: 0; line-height: 1.0;
}}
.vb-hero-sub {{
  font-size: clamp(13px, 1.6vw, 16px); color: #8A9098; text-align: center;
  margin: 14px 0 0; line-height: 1.6;
}}
/* Search input — larger, pill-ish, centered feel */
.vb-search .stTextInput input {{
  height: 58px !important; font-size: 17px !important;
  border-radius: 15px !important; border: 1.5px solid #E4E3DD !important;
  padding-left: 46px !important; background: #fff !important;
  box-shadow: 0 1px 2px rgba(20,30,40,.04), 0 12px 30px rgba(20,30,40,.05) !important;
}}
.vb-search .stTextInput input:focus {{
  border-color: {ACCENT} !important; box-shadow: 0 0 0 4px {ACCENT_RING} !important;
}}
.vb-search {{ position: relative; }}
.vb-search::before {{
  content: "🔍"; position: absolute; left: 16px; top: 40px; z-index: 5;
  font-size: 16px; opacity: .55; pointer-events: none;
}}
/* Suggestion rows rendered as secondary buttons */
.vb-suggest .stButton > button {{
  text-align: left !important; justify-content: flex-start !important;
  border: 1px solid #EEEDE7 !important; background: #fff !important;
  border-radius: 12px !important; padding: 12px 16px !important;
  font-weight: 600 !important; color: #16202B !important;
  box-shadow: 0 1px 2px rgba(20,30,40,.03) !important;
}}
.vb-suggest .stButton > button:hover {{
  background: #F7F3F6 !important; border-color: {ACCENT} !important;
}}
/* Loading card */
@keyframes vb-spin {{ to {{ transform: rotate(360deg); }} }}
.vb-load-card {{
  max-width: 460px; margin: 40px auto; background: #fff;
  border: 1px solid #E9E8E2; border-radius: 22px; padding: 32px 34px;
  box-shadow: 0 1px 2px rgba(20,30,40,.04), 0 24px 60px rgba(20,30,40,.10);
}}
.vb-load-title {{ font-size: 22px; font-weight: 800; color: #16202B; margin: 0; }}
.vb-load-sub {{ font-size: 13px; color: #8A9098; margin: 4px 0 22px; }}
.vb-step-row {{ display: flex; align-items: center; gap: 14px; padding: 9px 0; }}
.vb-step-done {{
  width: 28px; height: 28px; border-radius: 50%; background: {ACCENT};
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-size: 14px; flex: none;
}}
.vb-step-active {{
  width: 24px; height: 24px; border-radius: 50%; border: 3px solid {ACCENT_RING};
  border-top-color: {ACCENT}; animation: vb-spin .8s linear infinite; flex: none;
  margin: 2px;
}}
.vb-step-todo {{
  width: 26px; height: 26px; border-radius: 50%; border: 2px solid #E4E3DD;
  flex: none; margin: 1px;
}}
.vb-step-label {{ font-size: 15px; font-weight: 700; color: #16202B; }}
.vb-step-label-todo {{ font-size: 15px; font-weight: 600; color: #C5C4BC; }}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DB connection
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def _conn():
    c = db.get_conn()
    db.init_db(c)
    return c


conn = _conn()


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
def _all_facility_names() -> list[str]:
    return analysis.facility_names(conn)


def _facility_card(name: str) -> None:
    """Render a facility info card with key stats."""
    stats = db.facility_stats(conn, name)
    if not stats:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("口コミ数", f"{stats['n_reviews']} 件")
    c2.metric("本文あり", f"{stats['n_text_reviews']} 件")
    c3.metric(
        "平均評点",
        f"★{stats['avg_rating']}" if stats["avg_rating"] else "-",
    )
    c4.metric(
        "スコア軸",
        f"{len(stats['score_axes'])} 軸" if stats["score_axes"] else "なし",
    )
    if stats["date_oldest"] != "-":
        st.caption(f"口コミ期間: {stats['date_oldest']} 〜 {stats['date_newest']}")


_LOADING_STEPS = [
    "口コミデータを収集中",
    "評価スコアを集計中",
    "ポジ／ネガの感情を分析中",
    "トピックを分類中（TF-IDF）",
    "競合と比較中",
    "レポートを生成中",
]


def _loading_card_html(current: int, detail: str = "") -> str:
    """Full-screen loading overlay with the 6-step list + numeric progress.

    Rendered as a fixed, opaque overlay so nothing behind shows through.
    """
    total = len(_LOADING_STEPS)
    done = min(current, total)
    pct = round(100 * done / total)

    rows = []
    for i, label in enumerate(_LOADING_STEPS):
        if i < current:
            icon = '<div class="vb-step-done">✓</div>'
            lab = f'<div class="vb-step-label">{label}</div>'
        elif i == current:
            icon = '<div class="vb-step-active"></div>'
            lab = f'<div class="vb-step-label">{label}</div>'
        else:
            icon = '<div class="vb-step-todo"></div>'
            lab = f'<div class="vb-step-label-todo">{label}</div>'
        rows.append(f'<div class="vb-step-row">{icon}{lab}</div>')

    detail_html = (
        f'<div style="font-size:12px;color:#8A9098;margin-top:14px;text-align:center;">{detail}</div>'
        if detail else ""
    )
    progress = (
        '<div style="margin:4px 0 18px;">'
        '<div style="display:flex;justify-content:space-between;align-items:baseline;'
        'font-size:12.5px;font-weight:700;color:#5B6672;margin-bottom:8px;">'
        f'<span>{done} / {total} ステップ完了</span>'
        f'<span style="font-size:18px;font-weight:800;color:{ACCENT};">{pct}%</span></div>'
        '<div style="height:9px;background:#F1F0EA;border-radius:99px;overflow:hidden;">'
        f'<div style="height:100%;width:{pct}%;background:{ACCENT};border-radius:99px;transition:width .3s ease;"></div>'
        '</div></div>'
    )
    return (
        '<div style="position:fixed;inset:0;z-index:2147483000;background:#F7F7F4;'
        'display:flex;align-items:center;justify-content:center;padding:20px;">'
        '<div class="vb-load-card" style="margin:0;">'
        '<div class="vb-load-title">口コミを解析しています…</div>'
        '<div class="vb-load-sub">評価・感情・キーワードを集計中</div>'
        + progress
        + "".join(rows)
        + detail_html
        + "</div></div>"
    )


def _review_counts() -> dict[str, int]:
    """name -> review count (single query, for search suggestions)."""
    rows = conn.execute(
        """SELECT f.name, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id
           GROUP BY f.id""",
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _facility_meta() -> dict[str, str]:
    """name -> sub-line (category, else review count) for the search dropdown."""
    rows = conn.execute(
        """SELECT f.name, f.category, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id GROUP BY f.id""",
    ).fetchall()
    out = {}
    for name, cat, cnt in rows:
        out[name] = cat if cat else (f"口コミ {cnt}件" if cnt else "口コミ未登録")
    return out


def _selected_card_html(name: str, meta: dict[str, str]) -> str:
    """Selected-facility card (magenta ring + tinted icon + name + area)."""
    sub = meta.get(name, "")
    return (
        f'<div style="display:flex;align-items:center;gap:14px;padding:16px 18px;'
        f'border:2px solid {ACCENT};border-radius:16px;background:#fff;'
        'box-shadow:0 1px 2px rgba(20,30,40,.04),0 12px 30px rgba(20,30,40,.05);">'
        f'<span style="width:46px;height:46px;flex:none;border-radius:12px;background:{ACCENT_SOFT};'
        f'color:{ACCENT};display:flex;align-items:center;justify-content:center;'
        f'font-weight:800;font-size:18px;">{escape(name[:1])}</span>'
        '<span style="flex:1;min-width:0;display:flex;flex-direction:column;">'
        f'<span style="font-weight:800;font-size:17px;color:#16202B;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">{escape(name)}</span>'
        f'<span style="font-size:13px;color:#8A9098;margin-top:2px;">{escape(sub)}</span></span></div>'
    )


def _topic_sig() -> tuple:
    """Data signature so the topic matrix cache invalidates when reviews change."""
    rows = conn.execute(
        """SELECT f.name, COUNT(r.id) FROM facility f
           LEFT JOIN review r ON r.facility_id = f.id GROUP BY f.id""",
    ).fetchall()
    return tuple(sorted((r[0], r[1]) for r in rows))


@st.cache_data(show_spinner=False)
def _topic_matrix_cached(sig):
    """{facility: TopicScoreResult} for all facilities (heavy → cached by data sig)."""
    names = analysis.facility_names(conn)
    return topic_score.facility_topic_matrix(conn, names)


@st.cache_data(show_spinner=False)
def _photo_from_db(fid: int, sig):
    """(bytes, mime) or None — cached BLOB fetch (sig=updated_at invalidates)."""
    d = db.get_photo(conn, fid)
    return (d["image"], d["mime"]) if d else None


@st.cache_data(show_spinner=False)
def _infer_facilities_cached(file_bytes: bytes):
    """施設推定はファイル全体を再解析するため重い。チェック操作のたびに走ると
    大きなCSVでプロセスが落ちる → ファイル内容でキャッシュ（返り値は小さいサマリ）。"""
    return review_csv.infer_facilities(io.BytesIO(file_bytes))


@st.cache_data(show_spinner=False, max_entries=8)
def _parse_reviews_cached(file_bytes: bytes, facility_key):
    """単一施設プレビューの再解析（テキスト入力の再実行ごと）を防ぐためキャッシュ。
    max_entries でメモリを抑制。複数施設の保存ループでは使わない（1件ずつ処理）。"""
    return review_csv.parse_reviews(io.BytesIO(file_bytes), facility_key=facility_key)


# ─────────────────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS MODE
# ═════════════════════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state["app_mode"] == "analysis":

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
                                use_container_width=True,
                            ):
                                st.session_state["an_target"] = _n
                                st.rerun()
                    else:
                        st.caption("一致する施設が見つかりません。")

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
                                     use_container_width=True, key="an_run"):
                            st.session_state["an_screen"] = "running"
                            st.rerun()
                    else:
                        st.warning("この施設には口コミデータがありません。")
                    if st.button("← 施設を選び直す", use_container_width=True, key="an_reselect"):
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
            if st.button("← 設定に戻る", key="an_back_top", use_container_width=True):
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
                        use_container_width=True,
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
                            st.image(_photo_bytes, use_container_width=True)
                        else:
                            st.markdown(
                                '<div style="aspect-ratio:1;border-radius:12px;background:#F1F0EA;'
                                'display:flex;align-items:center;justify-content:center;color:#A7ABB0;">施設写真</div>',
                                unsafe_allow_html=True)
                        _has_db_photo = bool(_fid and db.photo_updated_at(conn, _fid))
                        _b1, _b2 = st.columns(2)
                        with _b1:
                            if st.button("💾 保存", key=f"prof_save_{_target}",
                                         disabled=not (_photo_bytes and _fid), use_container_width=True):
                                db.save_photo(conn, _fid, _photo_bytes, _photo_mime)
                                _photo_from_db.clear()
                                st.success("DBに保存しました。")
                                st.rerun()
                        with _b2:
                            if st.button("🗑️ 削除", key=f"prof_del_{_target}",
                                         disabled=not _has_db_photo, use_container_width=True):
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
                                     use_container_width=True,
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
                                     use_container_width=True, key=f"prof_regen_{_target}"):
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
                        if st.button("✓ 編集を終える（プレビューに戻る）", use_container_width=True,
                                     key=f"prof_done_{_target}"):
                            st.session_state[_ekey] = False
                            st.rerun()
            else:
                st.markdown(preview.html_profile(_bundle), unsafe_allow_html=True)
                _pe1, _pe2, _pe3 = st.columns([1, 1.4, 1])
                with _pe2:
                    if st.button("✏️ PROFILEを編集（写真・住所など）", use_container_width=True,
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
                st.dataframe(_df, use_container_width=True, hide_index=True)
                st.plotly_chart(
                    charts.topic_salience_bar(_ts), use_container_width=True, key="an_ts_sal"
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


# ─────────────────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════
# ADMIN MODE
# ═════════════════════════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────────────────────
else:
    _page = st.session_state["admin_page"]

    # ══════════════════════════════════════════════════════════════════════ #
    # ダッシュボード
    # ══════════════════════════════════════════════════════════════════════ #
    if _page == "dashboard":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">ダッシュボード</h1>',
            unsafe_allow_html=True,
        )

        overview = db.facility_overview(conn)
        n_fac = len(overview)
        n_reviews = sum(r["口コミ数"] for r in overview)
        n_no_data = sum(1 for r in overview if r["口コミ数"] == 0)

        _kc1, _kc2, _kc3, _kc4 = st.columns(4)
        _kc1.metric("登録施設", f"{n_fac} 件")
        _kc2.metric("総口コミ", f"{n_reviews} 件")
        _kc3.metric("未分析施設", f"{n_no_data} 件")
        _kc4.metric("アプリバージョン", config.APP_VERSION)

        if overview:
            st.divider()
            st.subheader("施設別の口コミ件数")
            _df = pd.DataFrame(overview)[["施設名", "口コミ数"]].sort_values(
                "口コミ数", ascending=False
            ).head(10)
            _fig = px.bar(
                _df, x="施設名", y="口コミ数",
                color_discrete_sequence=[ACCENT],
                height=320,
            )
            _fig.update_layout(
                plot_bgcolor="#F7F7F4",
                paper_bgcolor="#F7F7F4",
                margin=dict(t=10, b=10, l=0, r=0),
                xaxis=dict(tickangle=-30),
            )
            st.plotly_chart(_fig, use_container_width=True)

            st.divider()
            st.subheader("施設一覧")
            st.dataframe(
                pd.DataFrame(overview).drop(columns=["id"]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(
                "まだデータがありません。「📥 データ取り込み」からCSVを投入してください。"
            )

    # ══════════════════════════════════════════════════════════════════════ #
    # 施設管理
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "facilities":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">施設管理</h1>',
            unsafe_allow_html=True,
        )
        overview = db.facility_overview(conn)
        if not overview:
            st.info("まだデータがありません。")
            st.markdown("👉 **📥 データ取り込み** から口コミCSVを投入してください。")
        else:
            st.dataframe(
                pd.DataFrame(overview).drop(columns=["id"]),
                use_container_width=True,
                hide_index=True,
            )

            st.divider()
            st.subheader("施設の操作")
            _del_names = [f["施設名"] for f in overview]
            _dc1, _dc2 = st.columns([3, 1])
            with _dc1:
                _del_target = st.selectbox("操作対象の施設", _del_names, key="del_target")
            with _dc2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🗑️ 削除", key="del_btn", type="secondary"):
                    st.session_state["del_confirm"] = _del_target

            if st.session_state.get("del_confirm") == _del_target:
                st.warning(
                    f"「{_del_target}」とその口コミデータをすべて削除します。元に戻せません。"
                )
                _yc1, _yc2 = st.columns(2)
                with _yc1:
                    if st.button("⚠️ はい、削除する", type="primary", key="del_yes"):
                        _del_fid = conn.execute(
                            "SELECT id FROM facility WHERE name = ?", (_del_target,)
                        ).fetchone()
                        if _del_fid:
                            db.delete_facility(conn, _del_fid["id"])
                        st.session_state.pop("del_confirm", None)
                        st.success(f"「{_del_target}」を削除しました。")
                        st.rerun()
                with _yc2:
                    if st.button("キャンセル", key="del_no"):
                        st.session_state.pop("del_confirm", None)
                        st.rerun()

    # ══════════════════════════════════════════════════════════════════════ #
    # データ取り込み
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "import":
        st.markdown(
            '<div class="vb-step">管理モード</div>'
            '<h1 class="vb-h1">データ取り込み</h1>',
            unsafe_allow_html=True,
        )
        tab_csv, tab_excel = st.tabs(["📄 口コミ CSV", "📊 スコア Excel"])

        # ── CSV tab ─────────────────────────────────────────────────────── #
        with tab_csv:
            st.caption(
                "KAIZODE などからDLした口コミCSV/TSVを投げ込みます（施設名は手入力）。"
            )

            uploaded = st.file_uploader(
                "口コミ CSV / TSV", type=["csv", "tsv", "txt"], key="csv_upload"
            )

            inferred = []
            if uploaded:
                # ファイル内容でキャッシュ（チェック操作の再実行ごとに再解析しない）
                try:
                    inferred = _infer_facilities_cached(uploaded.getvalue())
                except Exception:
                    inferred = []

            if len(inferred) > 1:
                sel_key = "csv_facilities_checked"
                inferred_keys = {f["key"] for f in inferred}
                if sel_key not in st.session_state or set(st.session_state[sel_key]) != inferred_keys:
                    st.session_state[sel_key] = {f["key"]: True for f in inferred}

                st.markdown(f"**{len(inferred)} 施設が見つかりました。取り込む施設を選んでください。**")
                c1, c2, _ = st.columns([1, 1, 3])
                with c1:
                    if st.button("✅ すべて選択", use_container_width=True):
                        for k in st.session_state[sel_key]:
                            st.session_state[sel_key][k] = True
                        st.rerun()
                with c2:
                    if st.button("☐ すべて解除", use_container_width=True):
                        for k in st.session_state[sel_key]:
                            st.session_state[sel_key][k] = False
                        st.rerun()

                st.markdown("")
                for _f in inferred:
                    _r = f"★{_f['avg_rating']}" if _f["avg_rating"] else ""
                    label = f"**{_f['name']}** — {_f['count']}件　{_r}"
                    st.session_state[sel_key][_f["key"]] = st.checkbox(
                        label,
                        value=st.session_state[sel_key].get(_f["key"], True),
                        key=f"fac_check_{_f['key']}",
                    )

                selected_fac = [f for f in inferred if st.session_state[sel_key].get(f["key"], False)]
                st.divider()

                if selected_fac:
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        ftype_label = st.radio(
                            "種別",
                            list(config.FACILITY_TYPES.values()),
                            horizontal=True,
                            key="csv_ftype_multi",
                        )
                    ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

                    if st.button(
                        f"💾 {len(selected_fac)} 施設を保存する",
                        type="primary", use_container_width=True, key="csv_save_multi",
                    ):
                        with st.status(
                            f"保存中... 0 / {len(selected_fac)} 完了", expanded=True
                        ) as status:
                            for i, chosen_fac in enumerate(selected_fac, 1):
                                with st.status(
                                    f"🔄 {chosen_fac['name']} 処理中...", expanded=False
                                ) as fac_status:
                                    try:
                                        st.write(f"📖 データを解析中...")
                                        result = review_csv.parse_reviews(
                                            uploaded, facility_key=chosen_fac["key"]
                                        )
                                        uploaded.seek(0)
                                        st.write(f"✅ {len(result.reviews)} 件のパース完了")
                                    except Exception as e:
                                        st.error(f"パース失敗: {e}")
                                        fac_status.update(
                                            label=f"❌ {chosen_fac['name']} パース失敗",
                                            state="error",
                                        )
                                        continue

                                    try:
                                        st.write("💾 DB に保存中...")
                                        fid = db.upsert_facility(
                                            conn, chosen_fac["name"], ftype=ftype,
                                            category=result.category,
                                            general_rating=result.general_rating,
                                            total_reviews=result.total_reviews,
                                        )
                                        n_total = len(result.reviews)
                                        _pb = st.progress(0, text=f"0 / {n_total} 件")
                                        inserted, skipped = db.insert_reviews(
                                            conn, fid, result.reviews,
                                            progress_callback=lambda cur, tot, pb=_pb: pb.progress(
                                                cur / tot, text=f"{cur} / {tot} 件保存中..."
                                            ),
                                        )
                                        _pb.empty()
                                        st.write(
                                            f"✅ {inserted} 件保存（重複 {skipped} 件スキップ）"
                                        )
                                    except Exception as e:
                                        st.error(f"DB保存失敗: {e}")
                                        fac_status.update(
                                            label=f"❌ {chosen_fac['name']} 保存失敗",
                                            state="error",
                                        )
                                        continue

                                    try:
                                        st.write("🔢 定量スコアを算出中...")
                                        n_axes = scoring.compute_and_store(conn, fid)
                                        if n_axes:
                                            st.write(f"✅ {n_axes} 軸のスコアを算出")
                                    except Exception as e:
                                        st.warning(f"スコア算出スキップ: {e}")

                                    fac_status.update(
                                        label=f"✅ {chosen_fac['name']} 完了（{inserted}件保存）",
                                        state="complete",
                                    )

                                status.update(label=f"保存中... {i} / {len(selected_fac)} 完了")

                            status.update(
                                label=f"✅ {len(selected_fac)} 施設の保存が完了しました",
                                state="complete",
                            )
                        st.balloons()
                else:
                    st.warning("施設を1つ以上選択してください。")

            elif len(inferred) == 1:
                _f = inferred[0]
                _r = f" / 平均 ★{_f['avg_rating']}" if _f["avg_rating"] else ""
                st.info(f"📍 推定施設: **{_f['name']}** — {_f['count']}件{_r}")
                if _f["name"] and not st.session_state.get("csv_fac_confirm"):
                    if st.button(f"施設名に「{_f['name']}」を使う", key="autofill_single"):
                        st.session_state["csv_fac_confirm"] = _f["name"]
                        st.rerun()

                col1, col2 = st.columns(2)
                with col1:
                    facility_name_input = st.text_input(
                        "施設名（手入力・必須）",
                        placeholder="例: 風の海",
                        key="csv_fac_input",
                    )
                with col2:
                    ftype_label = st.radio(
                        "種別", list(config.FACILITY_TYPES.values()), horizontal=True
                    )
                ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)

                if facility_name_input.strip():
                    existing = analysis.facility_names(conn)
                    hints = search.suggest(facility_name_input.strip(), existing)
                    if hints:
                        st.info("DBにこんな施設が見つかりました")
                        cols = st.columns(len(hints))
                        for col, h in zip(cols, hints):
                            with col:
                                if st.button(f"✅ {h}", key=f"hint_{h}"):
                                    st.session_state["csv_fac_confirm"] = h

                facility_name = st.session_state.get(
                    "csv_fac_confirm", facility_name_input
                ).strip()

                if facility_name and facility_name != facility_name_input.strip():
                    st.success(f"施設名: **{facility_name}** を使用します")

                if uploaded and facility_name:
                    try:
                        result = _parse_reviews_cached(uploaded.getvalue(), _f["key"])
                    except Exception as e:
                        st.error(f"パースに失敗しました: {e}")
                        st.stop()

                    st.success(
                        f"解析: {len(result.reviews)} 件の口コミ "
                        f"（生 {result.n_raw} 行 / スキップ {result.n_skipped} 行）"
                    )
                    m1, m2, m3 = st.columns(3)
                    m1.metric("総合評点", result.general_rating or "-")
                    m2.metric("口コミ総数(施設)", result.total_reviews or "-")
                    m3.metric("カテゴリ", result.category or "-")

                    preview = pd.DataFrame([
                        {
                            "★": r.rating,
                            "日付": r.review_date[:10] if len(r.review_date) >= 10 else r.review_date,
                            "本文": (r.text[:60] + "…") if len(r.text) > 60 else r.text,
                            "サブスコア": ", ".join(f"{a}:{int(v)}" for a, v in r.subscores) or "-",
                        }
                        for r in result.reviews[:20]
                    ])
                    st.dataframe(preview, use_container_width=True, hide_index=True)

                    if st.button("💾 DBに保存", type="primary", key="csv_save"):
                        fid = db.upsert_facility(
                            conn, facility_name, ftype=ftype,
                            category=result.category,
                            general_rating=result.general_rating,
                            total_reviews=result.total_reviews,
                        )
                        inserted, skipped = db.insert_reviews(conn, fid, result.reviews)
                        n_axes = scoring.compute_and_store(conn, fid)
                        st.success(
                            f"✅ 「{facility_name}」に {inserted} 件保存"
                            f"（重複スキップ {skipped} 件）"
                            + (f" / 定量スコア {n_axes} 軸を自動算出しました" if n_axes else "")
                        )
                        st.session_state.pop("csv_fac_confirm", None)
                elif uploaded and not facility_name:
                    st.warning("先に施設名を入力してください。")

            elif uploaded:
                col1, col2 = st.columns(2)
                with col1:
                    facility_name_input = st.text_input(
                        "施設名（手入力・必須）",
                        placeholder="例: 風の海",
                        key="csv_fac_input_manual",
                    )
                with col2:
                    ftype_label = st.radio(
                        "種別", list(config.FACILITY_TYPES.values()), horizontal=True
                    )
                ftype = next(k for k, v in config.FACILITY_TYPES.items() if v == ftype_label)
                facility_name = facility_name_input.strip()

                if facility_name:
                    try:
                        result = _parse_reviews_cached(uploaded.getvalue(), None)
                    except Exception as e:
                        st.error(f"パースに失敗しました: {e}")
                        st.stop()

                    st.success(
                        f"解析: {len(result.reviews)} 件の口コミ "
                        f"（生 {result.n_raw} 行 / スキップ {result.n_skipped} 行）"
                    )
                    preview = pd.DataFrame([
                        {
                            "★": r.rating,
                            "日付": r.review_date[:10] if len(r.review_date) >= 10 else r.review_date,
                            "本文": (r.text[:60] + "…") if len(r.text) > 60 else r.text,
                        }
                        for r in result.reviews[:20]
                    ])
                    st.dataframe(preview, use_container_width=True, hide_index=True)

                    if st.button("💾 DBに保存", type="primary", key="csv_save_manual"):
                        fid = db.upsert_facility(
                            conn, facility_name, ftype=ftype,
                            category=result.category,
                            general_rating=result.general_rating,
                            total_reviews=result.total_reviews,
                        )
                        inserted, skipped = db.insert_reviews(conn, fid, result.reviews)
                        n_axes = scoring.compute_and_store(conn, fid)
                        st.success(
                            f"✅ 「{facility_name}」に {inserted} 件保存"
                            f"（重複スキップ {skipped} 件）"
                            + (f" / 定量スコア {n_axes} 軸を自動算出しました" if n_axes else "")
                        )

        # ── Excel tab ───────────────────────────────────────────────────── #
        with tab_excel:
            st.caption("既存の定量化指標 Excel を投げ込み → 列を確認して保存。")
            uploaded_xl = st.file_uploader(
                "スコア Excel / CSV", type=["xlsx", "xls", "csv"], key="xl_upload"
            )
            if uploaded_xl:
                try:
                    df = score_excel.read_table(uploaded_xl, filename=uploaded_xl.name)
                except Exception as e:
                    st.error(f"読み込みに失敗しました: {e}")
                    st.stop()

                st.subheader("プレビュー")
                st.dataframe(df.head(20), use_container_width=True)

                guess = score_excel.guess_columns(df)
                if guess.layout == "long":
                    st.info("縦持ち（施設・指標・値）の形式と判定しました。")

                cols = list(df.columns)
                name_col = st.selectbox(
                    "施設名の列", cols,
                    index=cols.index(guess.name_col) if guess.name_col in cols else 0,
                )
                if guess.layout == "long":
                    axis_col = st.selectbox(
                        "指標名の列", cols,
                        index=cols.index(guess.long_axis_col) if guess.long_axis_col in cols else 0,
                    )
                    value_col = st.selectbox(
                        "値の列", cols,
                        index=cols.index(guess.long_value_col) if guess.long_value_col in cols else 0,
                    )
                    scores = score_excel.extract_scores_long(df, name_col, axis_col, value_col)
                else:
                    axis_cols = st.multiselect(
                        "スコア指標の列",
                        [c for c in cols if c != name_col],
                        default=[c for c in guess.numeric_cols if c != name_col],
                    )
                    scores = score_excel.extract_scores_wide(df, name_col, axis_cols)

                scale = st.number_input(
                    "スケール", min_value=1.0,
                    value=float(guess.suggested_scale or 5.0), step=1.0,
                )

                if scores:
                    st.subheader("保存される内容")
                    st.dataframe(
                        pd.DataFrame(scores).T.rename_axis("施設名").reset_index(),
                        use_container_width=True, hide_index=True,
                    )
                    if st.button("💾 スコアをDBに保存", type="primary", key="xl_save"):
                        total = 0
                        for fname, axes in scores.items():
                            fid = db.upsert_facility(conn, fname)
                            total += db.upsert_scores(conn, fid, axes, scale=scale)
                        st.success(
                            f"✅ {len(scores)} 施設 / {total} 指標を保存しました。"
                        )
                else:
                    st.warning("数値の指標列が見つかりません。列マッピングを確認してください。")

    # ══════════════════════════════════════════════════════════════════════ #
    # トピックスコア（独自指標）
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "topic":
        st.markdown(
            '<div class="vb-step">独自指標</div>'
            '<h1 class="vb-h1">感情・トピック統合スコア</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "口コミを文単位でポジ／ネガ評価し、トピック確率で重み付けした独自指標。"
            "各トピック（指標軸）ごとに「どれだけ語られ、どう評価されているか」を可視化します。"
        )

        _tnames = analysis.facility_names(conn)
        if not _tnames:
            st.info("施設データがありません。")
            st.stop()

        _tt = st.selectbox(
            "対象施設", _tnames,
            index=_tnames.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in _tnames else 0,
            key="topic_fac",
        )
        st.session_state["analysis_target"] = _tt

        with st.spinner("感情・トピック統合スコアを算出中…"):
            _tres = topic_score.analyze_facility(conn, _tt)

        if _tres.empty:
            st.warning("トピックスコアの算出には本文付きの口コミが必要です。")
        else:
            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("総合感情スコア", f"{_tres.weighted_sentiment_100:.0f} / 100")
            _c2.metric("分析文数", f"{_tres.n_sentences} 文")
            _c3.metric("レビュー数", f"{_tres.n_reviews} 件")
            _best = _tres.sorted_by_sentiment()[0] if _tres.topics else None
            _c4.metric("最高評価の観点", _best.name if _best else "-")

            _tsent = _tres.sentiment_by_topic()
            _tnames = [t for t in topic_score.TOPIC_ORDER if t in _tsent]
            st.plotly_chart(
                charts.topic_matrix_bar(
                    _tnames, [_tsent[t] for t in _tnames],
                    overall_value=_tres.weighted_sentiment_100,
                ),
                use_container_width=True, key="adm_ts_bar",
            )

            _cl, _cr = st.columns([3, 2])
            with _cl:
                st.markdown("**トピック別の詳細**")
                _df = pd.DataFrame([
                    {
                        "トピック（指標軸）": t.name,
                        "感情スコア": round(t.sentiment_100, 1),
                        "言及度(%)": round(t.salience_pct, 1),
                        "統合スコア": round(t.avg_score, 4),
                        "重み": round(t.weight, 3),
                    }
                    for t in _tres.sorted_by_sentiment()
                ])
                st.dataframe(_df, use_container_width=True, hide_index=True)
            with _cr:
                st.markdown("**言及度（話題の量）**")
                st.plotly_chart(
                    charts.topic_salience_bar(_tres), use_container_width=True, key="adm_ts_sal"
                )

            st.caption(
                f"モデル全体スコア Σ(avg×重み) = {_tres.overall_100} / 100 ・ "
                f"バックエンド: {_tres.backend}（軽量: TF-IDFコサイン / SBERT任意）"
            )
            with st.expander("この指標について（算出モデル）", expanded=False):
                st.markdown(
                    "- **感情値**: 各文をキーワード辞書でポジ／中立／ネガ評価 → "
                    "温度スケーリング（T=0.7）→ 非線形補正（α=0.7）→ 0〜1 に正規化\n"
                    "- **トピック確率**: 文とトピック説明の類似度を z-score → 適応温度 → "
                    "softmax → Top-kブースト\n"
                    "- **統合スコア**: 文×トピック = 感情値 × トピック確率 を、"
                    "レビュー→トピック→全体へ集計\n"
                    "- **感情スコア(表示)**: 各トピックを語るときの平均感情（50=中立）"
                )

    # ══════════════════════════════════════════════════════════════════════ #
    # 強み・弱み分析
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "score":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">強み・弱み分析</h1>',
            unsafe_allow_html=True,
        )

        mat = analysis.score_matrix(conn)
        if mat.empty:
            mat = analysis.google_matrix(conn)

        if mat.empty:
            st.info("スコアデータがありません。「📥 データ取り込み」でExcelを登録してください。")
            st.stop()

        all_names = list(mat.index)
        target_name = st.selectbox(
            "対象施設", all_names,
            index=all_names.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in all_names else 0,
        )
        st.session_state["analysis_target"] = target_name

        with st.expander("全施設スコア一覧（ヒートマップ）", expanded=False):
            st.plotly_chart(charts.score_heatmap(mat), use_container_width=True)

        st.divider()
        tab_a, tab_b, tab_c = st.tabs(
            ["A　比較施設の平均", "B　全体（DB内）の平均", "C　特定施設1つ"]
        )

        def _render(result: analysis.ComparisonResult | None, key: str) -> None:
            if result is None:
                st.warning("比較できるデータが不足しています。")
                return
            strengths, weaknesses = analysis.top_n(result.diff, n=5)
            col_l, col_r = st.columns(2)
            with col_l:
                st.subheader("レーダーチャート")
                st.plotly_chart(
                    charts.radar(result.target, result.baseline,
                                 result.target_label, result.baseline_label),
                    use_container_width=True, key=f"radar_{key}",
                )
            with col_r:
                st.subheader("差分バーチャート")
                st.plotly_chart(
                    charts.diff_bar(result.diff, result.target_label, result.baseline_label),
                    use_container_width=True, key=f"bar_{key}",
                )
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**💪 強み TOP5**")
                if not strengths.empty:
                    st.dataframe(strengths, use_container_width=True, hide_index=True)
                else:
                    st.caption("なし")
            with c2:
                st.markdown("**⚠️ 弱み TOP5**")
                if not weaknesses.empty:
                    st.dataframe(weaknesses, use_container_width=True, hide_index=True)
                else:
                    st.caption("なし")
            with st.expander("数値詳細", expanded=False):
                detail = pd.DataFrame({
                    "対象": result.target.round(1),
                    "比較基準": result.baseline.round(1),
                    "差": result.diff.round(1),
                })
                detail.index.name = "指標"
                st.dataframe(detail, use_container_width=True)

        with tab_a:
            st.caption("対象施設 vs 比較施設（「比較施設」として登録した施設）の平均")
            _render(analysis.build_comparison(conn, target_name, "comparison_avg"), "a")
        with tab_b:
            st.caption("対象施設 vs DB内の全施設平均（対象除く）")
            _render(analysis.build_comparison(conn, target_name, "all_avg"), "b")
        with tab_c:
            st.caption("対象施設 vs 特定の1施設")
            others = [n for n in all_names if n != target_name]
            if not others:
                st.warning("比較できる他の施設がありません。")
            else:
                specific = st.selectbox("比較する施設", others, key="spec")
                _render(
                    analysis.build_comparison(conn, target_name, "specific",
                                              specific_name=specific), "c"
                )

    # ══════════════════════════════════════════════════════════════════════ #
    # テキスト分析 & インサイト
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "text":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">テキスト分析 & インサイト</h1>',
            unsafe_allow_html=True,
        )

        all_names = analysis.facility_names(conn)
        if not all_names:
            st.info("施設データがありません。")
            st.stop()

        target_name = st.selectbox(
            "対象施設", all_names,
            index=all_names.index(st.session_state["analysis_target"])
            if st.session_state.get("analysis_target") in all_names else 0,
            key="text_fac",
        )
        st.session_state["analysis_target"] = target_name

        st.subheader("テキスト分析")
        with st.spinner("形態素解析 + TF-IDF 実行中…"):
            profile = text_analysis.build_profile(conn, target_name, top_n=20)

        if profile.empty:
            st.warning("口コミテキストがありません。")
        else:
            st.caption(f"分析対象: {profile.n_reviews} 件")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**TF-IDF キーワード TOP20**")
                if not profile.tfidf_keywords.empty:
                    fig = px.bar(
                        profile.tfidf_keywords.head(20), x="スコア", y="単語",
                        orientation="h", color="スコア",
                        color_continuous_scale=[[0, "#D9E8F0"], [1, ACCENT]],
                        height=500,
                    )
                    fig.update_layout(
                        yaxis=dict(autorange="reversed"),
                        coloraxis_showscale=False,
                        margin=dict(t=10, b=10),
                        plot_bgcolor="#F7F7F4",
                        paper_bgcolor="#F7F7F4",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            with col2:
                st.markdown("**頻出フレーズ（バイグラム）**")
                if not profile.bigrams.empty:
                    fig2 = px.bar(
                        profile.bigrams.head(20), x="件数", y="フレーズ",
                        orientation="h", color="件数",
                        color_continuous_scale=[[0, "#D5EBE2"], [1, "#4F8A6B"]],
                        height=500,
                    )
                    fig2.update_layout(
                        yaxis=dict(autorange="reversed"),
                        coloraxis_showscale=False,
                        margin=dict(t=10, b=10),
                        plot_bgcolor="#F7F7F4",
                        paper_bgcolor="#F7F7F4",
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("フレーズ抽出には口コミ件数がもう少し必要です。")

            with st.expander("トライグラム TOP20", expanded=False):
                if not profile.trigrams.empty:
                    st.dataframe(profile.trigrams, use_container_width=True, hide_index=True)
                else:
                    st.info("なし")

            with st.expander("代表口コミ", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**高評価 TOP3**")
                    for i, r in enumerate(profile.high_rated, 1):
                        st.text_area(f"{i}", r, height=120, key=f"hi_{i}", disabled=True)
                with c2:
                    st.markdown("**低評価 TOP3**")
                    if not profile.low_rated:
                        st.caption("低評価（3★以下）なし")
                    for i, r in enumerate(profile.low_rated, 1):
                        st.text_area(f"{i}", r, height=120, key=f"lo_{i}", disabled=True)

        st.divider()
        st.subheader("LLMインサイト")

        comp_res = (
            analysis.build_comparison(conn, target_name, "comparison_avg")
            or analysis.build_comparison(conn, target_name, "all_avg")
        )
        if comp_res:
            st.caption(f"スコア比較軸: {comp_res.baseline_label}")

        api_key = llm.get_api_key()
        if not api_key:
            st.info("Gemini API キー未設定。aistudio.google.com で無料取得できます。")
            api_key = st.text_input("Gemini API キー（セッション限り）", type="password")

        if not profile.empty:
            if st.button("✨ インサイトを生成する", type="primary", disabled=not api_key):
                kw = profile.tfidf_keywords["単語"].tolist()
                bi = (
                    profile.bigrams["フレーズ"].tolist()
                    if not profile.bigrams.empty else []
                )
                prompt = llm.build_prompt(
                    target_name,
                    comp_res.diff if comp_res else None,
                    kw, bi, profile.high_rated, profile.low_rated,
                )
                with st.spinner("Gemini が分析中…"):
                    result = llm.generate_insights(prompt, api_key)

                if result.error:
                    st.error(result.error)
                else:
                    st.session_state["insights"] = result
                    st.session_state["insights_facility"] = target_name
                    st.success("インサイト生成完了")
                    st.markdown(f"### まとめ\n{result.summary}")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**💪 強み**")
                        for item in result.strengths:
                            st.markdown(f"- {item}")
                    with c2:
                        st.markdown("**⚠️ 弱み**")
                        for item in result.weaknesses:
                            st.markdown(f"- {item}")
                    st.markdown("**💡 示唆**")
                    for item in result.implications:
                        st.markdown(f"- {item}")
                    st.markdown("**🔧 改善提案**")
                    for item in result.improvements:
                        st.markdown(f"- {item}")

    # ══════════════════════════════════════════════════════════════════════ #
    # レポート出力
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "report":
        st.markdown(
            '<div class="vb-step">詳細分析</div>'
            '<h1 class="vb-h1">レポート出力 (PPTX)</h1>',
            unsafe_allow_html=True,
        )
        st.caption("分析結果を PowerPoint にまとめてダウンロードします。")

        all_names = analysis.facility_names(conn)
        if not all_names:
            st.info("施設データがありません。")
            st.stop()

        col1, col2 = st.columns(2)
        with col1:
            target_name = st.selectbox(
                "対象施設", all_names,
                index=all_names.index(st.session_state["analysis_target"])
                if st.session_state.get("analysis_target") in all_names else 0,
                key="rep_fac",
            )
        with col2:
            axis_label = st.radio(
                "比較基準", ["比較施設の平均", "全体（DB内）の平均"], horizontal=True
            )
        axis = "comparison_avg" if axis_label == "比較施設の平均" else "all_avg"

        insights = None
        if st.session_state.get("insights_facility") == target_name:
            insights = st.session_state.get("insights")
            st.success("生成済みインサイトをレポートに含めます。")
        else:
            st.info("「💬 テキスト分析」でインサイトを生成するとレポートに反映されます。")

        if st.button("📑 レポート(PPTX)を生成", type="primary"):
            with st.spinner("スライドを生成中…"):
                tmp = Path(tempfile.mkdtemp()) / f"VoiceBaum_{target_name}.pptx"
                report.build_report(conn, target_name, axis=axis, insights=insights, output_path=tmp)
            with open(tmp, "rb") as f:
                st.download_button(
                    "⬇️ ダウンロード", data=f.read(),
                    file_name=tmp.name,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    type="primary",
                )
            st.success("生成完了。上のボタンからダウンロードしてください。")

    # ══════════════════════════════════════════════════════════════════════ #
    # CSVプロファイラ
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "profiler":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">CSVプロファイラ</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "CSVをアップロードするとデータ構造（列・型・統計・サンプル）を解析し、"
            "Claude に貼り付けられるプロンプトを生成します。"
        )

        _pf_upload = st.file_uploader(
            "CSV / TSV ファイル", type=["csv", "tsv", "txt"], key="pf_upload"
        )

        if _pf_upload:
            try:
                _pf_df = csv_profiler.load_df(_pf_upload)
                _pf_upload.seek(0)
            except Exception as _e:
                st.error(f"読み込みに失敗しました: {_e}")
                st.stop()

            st.success(f"読み込み完了: **{len(_pf_df)} 行 × {len(_pf_df.columns)} 列**")

            with st.expander("データプレビュー（先頭20行）", expanded=False):
                st.dataframe(_pf_df.head(20), use_container_width=True)

            _pf_question = st.text_area(
                "Claudeへの質問（省略可）",
                placeholder=(
                    "例: この口コミCSVの列構造を把握してください。\n"
                    "評価が空欄の行が多い理由と、テキスト分析に使える列を教えてください。"
                ),
                height=90,
                key="pf_question",
            )

            _pf_prompt = csv_profiler.build_claude_prompt(
                _pf_df,
                filename=getattr(_pf_upload, "name", ""),
                question=_pf_question,
            )

            st.subheader("Claude用プロンプト")
            st.caption(
                "以下のテキストをコピーして Claude（claude.ai など）に貼り付けてください。"
            )
            st.code(_pf_prompt, language="markdown")

    # ══════════════════════════════════════════════════════════════════════ #
    # KAIZODE連携（発注・状況確認・DB取り込み）※ログイン後のみ到達
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "kaizode":
        st.markdown(
            '<div class="vb-step">連携</div>'
            '<h1 class="vb-h1">KAIZODE連携</h1>',
            unsafe_allow_html=True,
        )
        st.caption(
            "KAIZODEにレビュー収集を発注し、解析完了分をDBへ取り込みます。"
            "レート制限（20リクエスト/分）には自動で対応します。"
        )

        # ── APIキーの解決（secrets/環境変数を推奨。無ければセッション限りの入力）─ #
        _kz_key = os.environ.get("KAIZODE_API_KEY", "")
        _key_src = "secrets/環境変数"
        if not _kz_key:
            try:
                _kz_key = st.secrets.get("KAIZODE_API_KEY", "")
            except Exception:
                _kz_key = ""
        if not _kz_key:
            _kz_key = st.session_state.get("kz_session_key", "")
            _key_src = "セッション入力"

        if not _kz_key:
            st.info(
                "KAIZODE APIキーが未設定です。恒久利用は secrets の `KAIZODE_API_KEY` を推奨。"
                "下で入力した場合は**このセッション限り**で使用し、DBやファイルには保存しません。"
            )
            _kz_in = st.text_input(
                "KAIZODE APIキー（セッション限り）", type="password", key="kz_key_input",
            )
            if st.button("このセッションで使用する", type="primary", key="kz_key_use"):
                if _kz_in.strip():
                    st.session_state["kz_session_key"] = _kz_in.strip()
                    st.rerun()
                else:
                    st.warning("APIキーを入力してください。")
            st.stop()

        _kc1, _kc2 = st.columns([3, 1])
        with _kc1:
            st.caption(f"🔑 APIキー: 設定済み（{_key_src}・末尾 …{_kz_key[-4:]}）")
        with _kc2:
            if _key_src == "セッション入力":
                if st.button("🔒 キーを破棄", key="kz_key_clear", use_container_width=True):
                    st.session_state.pop("kz_session_key", None)
                    st.rerun()

        _kz_client = kaizode.KaizodeClient(api_key=_kz_key)
        tab_kst, tab_knew, tab_ksync = st.tabs(
            ["📋 収集状況", "🛒 収集を発注", "⬇️ DBへ取り込み"]
        )

        # ── 収集状況 ────────────────────────────────────────────────── #
        with tab_kst:
            if st.button("🔄 最新の状況を取得", key="kz_refresh"):
                st.session_state.pop("kz_datasets", None)
            if "kz_datasets" not in st.session_state:
                with st.spinner("KAIZODEに問い合わせ中…"):
                    try:
                        st.session_state["kz_datasets"] = _kz_client.list_datasets()
                    except kaizode.KaizodeError as _e:
                        st.error(str(_e))
                        st.stop()
            _kz_dss = st.session_state.get("kz_datasets") or []
            if not _kz_dss:
                st.info("データセットがまだありません。「🛒 収集を発注」から作成してください。")
            else:
                st.dataframe(
                    pd.DataFrame([
                        {
                            "データセット": d.get("dataset_name", ""),
                            "状態": kaizode.STATUS_LABELS.get(d.get("status"), d.get("status")),
                            "定期": "✓" if d.get("is_scheduled") else "",
                            "更新": str(d.get("updated_at", ""))[:19],
                            "ID": d.get("dataset_id", ""),
                        }
                        for d in _kz_dss
                    ]),
                    use_container_width=True, hide_index=True,
                )
                st.caption("収集はKAIZODE側で非同期に進みます。「解析完了」になったら取り込めます。")

        # ── 収集を発注 ──────────────────────────────────────────────── #
        with tab_knew:
            st.caption("1行1施設で「施設名,レビューURL[,取得開始日]」を入力してください。")
            _kz_name = st.text_input("データセット名", value="口コミ対象", key="kz_ds_name")
            _kz_lines = st.text_area(
                "施設リスト", height=170, key="kz_lines",
                placeholder="容器文化ミュージアム,https://www.google.com/maps/...,2024-01-01\nトヨタ博物館,https://www.google.com/maps/...",
            )
            if st.button("🛒 収集を発注する", type="primary", key="kz_create"):
                _urls = []
                for _ln in _kz_lines.splitlines():
                    _parts = [p.strip() for p in _ln.split(",")]
                    if len(_parts) >= 2 and _parts[1]:
                        _item = {"url": _parts[1],
                                 "review_target_name": _parts[0] or None}
                        if len(_parts) >= 3 and _parts[2]:
                            _item["since"] = _parts[2]
                        _urls.append(_item)
                if not _urls:
                    st.warning("1件も読み取れませんでした。「施設名,URL」の形式で入力してください。")
                else:
                    try:
                        with st.spinner("データセットを作成中…"):
                            _ds = _kz_client.create_dataset(
                                _kz_name.strip() or "口コミ対象", _urls
                            )
                        st.success(
                            f"✅ {len(_urls)} 施設で発注しました"
                            f"（dataset_id: {_ds.get('dataset_id')}）。"
                            "収集完了後に「⬇️ DBへ取り込み」を実行してください。"
                        )
                        st.session_state.pop("kz_datasets", None)
                    except kaizode.KaizodeError as _e:
                        st.error(str(_e))

        # ── DBへ取り込み ────────────────────────────────────────────── #
        with tab_ksync:
            _sc1, _sc2 = st.columns(2)
            with _sc1:
                _kz_cat = st.text_input(
                    "category（任意）", key="kz_cat", placeholder="例: 企業ミュージアム",
                )
            with _sc2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                _kz_full = st.checkbox("全件取り直し（通常は差分）", key="kz_full")
            if st.button("⬇️ 解析完了分をDBへ取り込む", type="primary", key="kz_sync"):
                _logbox = st.container(height=260)
                try:
                    with st.spinner("同期中…（件数により数分かかります）"):
                        _res = kaizode.sync_datasets(
                            _kz_client, conn,
                            category=(_kz_cat.strip() or None),
                            full=_kz_full, log=_logbox.write,
                        )
                    st.success(
                        f"✅ 完了: 新規 {_res['inserted']:,} 件 / "
                        f"重複 {_res['skipped_dup']:,} 件 / "
                        f"{_res['datasets_synced']} データセット"
                    )
                    _topic_matrix_cached.clear()
                except kaizode.KaizodeError as _e:
                    st.error(str(_e))
            st.caption(
                "差分取得: 前回取り込み以降のレビューだけをDLします（重複は自動スキップ）。"
            )

    # ══════════════════════════════════════════════════════════════════════ #
    # 連携設定
    # ══════════════════════════════════════════════════════════════════════ #
    elif _page == "integration":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">連携設定</h1>',
            unsafe_allow_html=True,
        )

        # DB connection status
        import os
        _turso_url = os.environ.get("TURSO_URL")
        if not _turso_url:
            try:
                _turso_url = st.secrets.get("TURSO_URL", None)
            except Exception:
                _turso_url = None

        if _turso_url:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                        background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                        margin-bottom:16px;">
              <div style="width:10px;height:10px;border-radius:50%;background:#4F8A6B;"></div>
              <div>
                <div style="font-weight:700;color:#16202B;">Turso (libSQL) — 接続済み</div>
                <div style="font-size:12px;color:#8A9098;margin-top:2px;">{_turso_url}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                        background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                        margin-bottom:16px;">
              <div style="width:10px;height:10px;border-radius:50%;background:#C9A24B;"></div>
              <div>
                <div style="font-weight:700;color:#16202B;">SQLite（ローカル）</div>
                <div style="font-size:12px;color:#8A9098;margin-top:2px;">
                  Turso 未設定 — ローカルの data/reviews.db を使用中
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        tab_schema, tab_guide = st.tabs(["📋 テーブルスキーマ", "📖 接続ガイド"])

        with tab_schema:
            st.code("""-- 施設マスタ
CREATE TABLE facility (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  name            TEXT NOT NULL UNIQUE,
  type            TEXT,                    -- 'target' | 'comparison'
  category        TEXT,
  general_rating  REAL,
  total_reviews   INTEGER
);

-- 口コミ本文
CREATE TABLE review (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  facility_id INTEGER REFERENCES facility(id),
  review_id   TEXT,
  review_date TEXT,
  rating      REAL,
  text        TEXT,
  source      TEXT,
  author      TEXT
);

-- Google観点別スコア（Rooms/Service/...）
CREATE TABLE review_subscore (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  review_db_id INTEGER REFERENCES review(id),
  axis        TEXT,
  value       REAL
);

-- 定量化指標（Excel取り込み / 自動算出）
CREATE TABLE score (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  facility_id  INTEGER REFERENCES facility(id),
  metric_name  TEXT,
  value        REAL,
  scale        REAL DEFAULT 5.0
);""", language="sql")

        with tab_guide:
            st.markdown("""
### Turso への接続設定

1. [turso.tech](https://turso.tech) でアカウントを作成
2. データベースを作成し、DB URL と Auth Token を取得
3. 以下のいずれかで設定:

**Streamlit Cloud の場合** (`.streamlit/secrets.toml`):
```toml
TURSO_URL = "libsql://your-db-xxx.turso.io"
TURSO_TOKEN = "eyJh..."
```

**ローカルの場合** (環境変数):
```bash
export TURSO_URL="libsql://your-db-xxx.turso.io"
export TURSO_TOKEN="eyJh..."
```

**Gemini API キー** (LLMインサイト機能):
```toml
GEMINI_API_KEY = "AIza..."
```
""")

            st.info(
                "Turso 未設定の場合はローカルの `data/reviews.db` を使用します。"
                "データはサーバー再起動で消えるためクラウドDBの設定を推奨します。"
            )

    elif _page == "account":
        st.markdown(
            '<div class="vb-step">ツール</div>'
            '<h1 class="vb-h1">アカウント</h1>',
            unsafe_allow_html=True,
        )

        _me = st.session_state.get("admin_email") or "—"
        _gate_signup = bool(auth.signup_code())
        _gate_master = bool(auth.admin_password())
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:12px;padding:16px 18px;
                    background:#fff;border:1px solid #E9E8E2;border-radius:12px;
                    margin-bottom:16px;">
          <div style="width:10px;height:10px;border-radius:50%;background:#4F8A6B;"></div>
          <div>
            <div style="font-weight:700;color:#16202B;">ログイン中: {escape(str(_me))}</div>
            <div style="font-size:12px;color:#8A9098;margin-top:2px;">
              招待コード(SIGNUP_CODE): {"設定済み ✅" if _gate_signup else "未設定 —（新規登録は無効）"}
              ／ 非常口(ADMIN_PASSWORD): {"設定済み ✅" if _gate_master else "未設定 —"}
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        tab_users, tab_add, tab_pw = st.tabs(
            ["👥 ユーザー一覧", "➕ ユーザー追加", "🔑 自分のパスワード変更"]
        )

        # ── ユーザー一覧 ─────────────────────────────────────────────── #
        with tab_users:
            try:
                _users = auth.list_users(conn)
            except Exception as _e:
                _users = []
                st.error(f"ユーザー一覧を取得できませんでした: {_e}")
            if not _users:
                st.caption("登録済みアカウントはまだありません。"
                           "（非常口パスワードでログイン中の可能性があります）")
            else:
                st.caption(f"{len(_users)} 件のアカウント")
                for _u in _users:
                    _uc1, _uc2, _uc3 = st.columns([3, 2, 1])
                    with _uc1:
                        st.markdown(
                            f"<div style='padding:8px 0;font-weight:600;color:#16202B;'>"
                            f"{escape(_u['email'])}</div>",
                            unsafe_allow_html=True,
                        )
                    with _uc2:
                        st.markdown(
                            f"<div style='padding:8px 0;font-size:12px;color:#8A9098;'>"
                            f"{escape(str(_u.get('created_at') or ''))[:10]}</div>",
                            unsafe_allow_html=True,
                        )
                    with _uc3:
                        _is_self = (auth.normalize_email(str(_me)) == _u["email"])
                        if st.button("削除", key=f"deluser_{_u['email']}",
                                     use_container_width=True, disabled=_is_self,
                                     help="ログイン中の自分は削除できません" if _is_self else None):
                            auth.delete_user(conn, _u["email"])
                            st.toast(f"{_u['email']} を削除しました。", icon="🗑️")
                            st.rerun()

        # ── ユーザー追加（ログイン済み管理者が招待コード無しで追加）──── #
        with tab_add:
            st.caption("ログイン中の管理者は、招待コードなしで新しいアカウントを追加できます。")
            with st.form("account_add_user"):
                _nem = st.text_input("メールアドレス", key="acc_add_email")
                _npw = st.text_input("パスワード（8文字以上）", type="password",
                                     key="acc_add_pw")
                _add = st.form_submit_button("➕ 追加", type="primary")
            if _add:
                try:
                    auth.create_user(conn, _nem, _npw)
                    st.success(f"{auth.normalize_email(_nem)} を追加しました。")
                    st.rerun()
                except auth.AuthError as _e:
                    st.error(str(_e))
                except Exception as _e:
                    st.error(f"追加に失敗しました: {_e}")

        # ── 自分のパスワード変更 ─────────────────────────────────────── #
        with tab_pw:
            _me_norm = auth.normalize_email(str(_me))
            _is_account = bool(_me_norm) and auth.user_exists(conn, _me_norm)
            if not _is_account:
                st.info("非常口パスワードでログイン中のため、ここでは変更できません。"
                        "アカウントを作成するとパスワードを管理できます。")
            else:
                with st.form("account_change_pw"):
                    _cur = st.text_input("現在のパスワード", type="password", key="acc_cur_pw")
                    _new1 = st.text_input("新しいパスワード（8文字以上）", type="password",
                                          key="acc_new_pw1")
                    _new2 = st.text_input("新しいパスワード（確認）", type="password",
                                          key="acc_new_pw2")
                    _chg = st.form_submit_button("🔑 変更", type="primary")
                if _chg:
                    if not auth.authenticate(conn, _me_norm, _cur):
                        time.sleep(1)
                        st.error("現在のパスワードが違います。")
                    elif _new1 != _new2:
                        st.error("新しいパスワード（確認）が一致しません。")
                    else:
                        try:
                            auth.set_password(conn, _me_norm, _new1)
                            st.success("パスワードを変更しました。")
                        except auth.AuthError as _e:
                            st.error(str(_e))
