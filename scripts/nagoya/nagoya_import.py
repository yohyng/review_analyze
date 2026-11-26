"""名古屋6館の口コミを DB に入れる（検証用。リポジトリにはコミットしない）。"""
import sys, os
sys.path.insert(0, "/home/user/review_analyze")
from pathlib import Path
import openpyxl
from src import db, review_csv

SCR = Path("/tmp/claude-0/-home-user-review-analyze/7c50c4d7-75ad-5183-b04f-e70d0b53634e/scratchpad")
XLSX = SCR / "nagoya_data" / "reviews_all.xlsx"
TARGET = "名古屋市科学館"

conn = db.get_conn(); db.init_db(conn)
wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
ws = wb.worksheets[0]
it = ws.iter_rows(values_only=True)
head = [str(c) for c in next(it)]
ix = {k: head.index(k) for k in ("place_name", "review", "review_date",
                                "review_rating", "category")}
by_fac: dict[str, list] = {}
for r in it:
    name = str(r[ix["place_name"]] or "").strip()
    text = str(r[ix["review"]] or "").strip()
    if not name or not text:
        continue
    date = str(r[ix["review_date"]] or "")[:10]
    try:
        rating = int(float(r[ix["review_rating"]]))
    except (TypeError, ValueError):
        rating = None
    # **投稿者名と URL は取り込まない**（2026-11-25 の決定）。
    by_fac.setdefault(name, []).append(review_csv.ParsedReview(
        review_id=review_csv.fallback_id(text, date, ""),
        rating=rating, text=text, review_date=date, reviewer_name="",
        local_guide=False, likes=None, owner_response="",
        owner_response_date="",
    ))

total = 0
for name, revs in by_fac.items():
    review_csv.disambiguate_ids(revs)
    ftype = "target" if name == TARGET else "comparison"
    fid = db.upsert_facility(conn, name, ftype=ftype, category="企業ミュージアム")
    ins, skip = db.insert_reviews(conn, fid, revs)
    print(f"  {name:20s} 投入 {ins:5d} / 重複 {skip:4d}  ({ftype})")
    total += ins
print(f"合計 {total:,} 件")
