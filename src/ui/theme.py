"""Global CSS / design tokens for the VoiceBAUM Streamlit UI.

Extracted verbatim from app.py so the design lives in one place and
app.py stays a thin orchestrator. inject_global_css() must be called
once, right after st.set_page_config().
"""
import streamlit as st

ACCENT = "#B0338A"
ACCENT_SOFT = "rgba(176,51,138,0.09)"
ACCENT_RING = "rgba(176,51,138,0.22)"


def inject_global_css() -> None:
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

