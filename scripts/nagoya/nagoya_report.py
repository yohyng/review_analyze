"""名古屋6館を分析してレポートを書き出す（検証用）。"""
import sys, time
sys.path.insert(0, "/home/user/review_analyze")
from pathlib import Path
from src import db, topic_score, preview, slides, scoring, report, report_v5, vffi

SCR = Path("/tmp/claude-0/-home-user-review-analyze/7c50c4d7-75ad-5183-b04f-e70d0b53634e/scratchpad")
TARGET = "名古屋市科学館"
PEERS = ["名古屋市美術館", "でんきの科学館", "トヨタ産業技術記念館",
         "JR東海　リニア・鉄道館", "名古屋港水族館"]

conn = db.get_conn(); db.init_db(conn)
names = [r["name"] for r in conn.execute("SELECT name FROM facility").fetchall()]
print("施設:", names)

t0 = time.time()
matrix = {}
for n in names:
    matrix[n] = topic_score.analyze_facility(conn, n)
    print(f"  {n:20s} {time.time()-t0:5.1f}s")

for n in names:
    fid = conn.execute("SELECT id FROM facility WHERE name=?", (n,)).fetchone()["id"]
    scoring.compute_and_store(conn, fid)

b = preview.build_bundle(conn, TARGET, matrix, None, None, peers_override=PEERS)

# ── 文章は Claude Code がこの場で執筆したものを流し込む（LLM は呼ばない）── #
sys.path.insert(0, str(SCR))
import nagoya_texts
from src import discussion
b["slide_summaries"] = nagoya_texts.SUMMARIES
_issues = b.get("issues") or []
_acts = discussion.apply_llm_result(_issues, nagoya_texts.DISCUSSION)
if _acts:
    b["actions"] = _acts
    print(f"ディスカッション: 課題{len(_issues)}件・打ち手{len(_acts)}件を反映")
else:
    print("!! ディスカッションの反映に失敗（件数が合わない可能性）")
print("\nバンドル:", b.get("n_reviews"), "件 / 比較", b.get("peer_names"))
print("順位:", b.get("rank"), "/", b.get("total_fac"))

html = slides.deck(b, detail=True)
page = ('<!doctype html><meta charset="utf-8">'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700;800&display=swap" rel="stylesheet">'
        '<style>*{box-sizing:border-box}body{margin:0;padding:20px;background:#F7F7F4;'
        'width:1600px;font-family:"Noto Sans JP",sans-serif}'
        '.vb-cv{margin-bottom:24px}</style>' + slides.TOOLTIP_CSS + "".join(html))
(SCR / "nagoya_report.html").write_text(page, encoding="utf-8")
print(f"スライド {len(html)} 枚 → nagoya_report.html")

report.build_report(conn, TARGET, output_path=str(SCR / "nagoya_report.pptx"))
revs = [(r["rating"], r["text"]) for r in conn.execute(
    "SELECT rating, text FROM review WHERE facility_id="
    "(SELECT id FROM facility WHERE name=?)", (TARGET,)).fetchall()]
report_v5.build_report_v5(report_v5.Ctx(
    target=TARGET, reviews=revs, vffi=vffi.assess(revs),
    baseline_label="比較5施設の平均"), SCR / "nagoya_report_v5.pptx")
print("PPTX 2本 書き出し完了")
