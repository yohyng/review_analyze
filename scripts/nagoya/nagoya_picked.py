"""対応済みのスライドだけを書き出す（検証用）。"""
import sys
sys.path.insert(0, "/home/user/review_analyze")
sys.path.insert(0, "/home/user/review_analyze/scripts/nagoya")
from pathlib import Path
from src import db, topic_score, preview, slides, scoring, discussion
import nagoya_texts

SCR = Path("/tmp/claude-0/-home-user-review-analyze/7c50c4d7-75ad-5183-b04f-e70d0b53634e/scratchpad")
TARGET = "名古屋市科学館"
PEERS = ["名古屋市美術館", "でんきの科学館", "トヨタ産業技術記念館",
         "JR東海　リニア・鉄道館", "名古屋港水族館"]

# このセッションで手を入れたスライドだけ
PICKED = [
    ("slide2_market_position",   "2 市場内ポジション"),
    ("slide3_competitor_compare", "3 指定競合との比較"),
    ("slide3_competitor_detail", "3 指定競合との比較（詳細）"),
    ("slide4_timeline",          "4 時間軸分析"),
    ("slide5_space_detail",      "5 空間体験分析（詳細）"),
    ("slide7_discussion",        "7 ディスカッションポイント"),
]

conn = db.get_conn(); db.init_db(conn)
names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
matrix = {n: topic_score.analyze_facility(conn, n) for n in names}
for n in names:
    fid = conn.execute("SELECT id FROM facility WHERE name=?", (n,)).fetchone()["id"]
    scoring.compute_and_store(conn, fid)

b = preview.build_bundle(conn, TARGET, matrix, None, None, peers_override=PEERS)
b["slide_summaries"] = nagoya_texts.SUMMARIES
_acts = discussion.apply_llm_result(b.get("issues") or [], nagoya_texts.DISCUSSION)
if _acts:
    b["actions"] = _acts

html = []
for fn, label in PICKED:
    h = getattr(slides, fn)(b)
    if h and h.strip():
        html.append(h)
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}（空）")

page = ('<!doctype html><meta charset="utf-8"><title>名古屋市科学館 レポート（対応分）</title>'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700;800&display=swap" rel="stylesheet">'
        '<style>*{box-sizing:border-box}body{margin:0;padding:20px;background:#F7F7F4;'
        'width:1600px;font-family:"Noto Sans JP",sans-serif}'
        '.vb-cv{margin-bottom:24px}</style>' + slides.TOOLTIP_CSS + "".join(html))
out = SCR / "nagoya_picked.html"
out.write_text(page, encoding="utf-8")
print(f"\n{len(html)} 枚 → {out}")
