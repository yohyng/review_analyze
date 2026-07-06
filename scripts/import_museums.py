#!/usr/bin/env python3
"""企業ミュージアム 46施設の口コミを DB（Turso または ローカルSQLite）へ取り込む。

データ: data/museums/reviews.csv.gz
  columns = place_name, reviewer_name, review_text, review_date, review_rating

  * すべての施設を category="企業ミュージアム" として登録
  * 「容器文化ミュージアム」を対象施設(ftype=target)、その他を比較施設(ftype=comparison)
  * review_id は (施設名+投稿者+日付+本文) の決定論ハッシュ → 再実行しても重複しない

接続先は src.db.get_conn() に従う:
  TURSO_URL + TURSO_TOKEN を環境変数/Secrets に設定していれば Turso、無ければローカル。

使い方:
  python scripts/import_museums.py                 # 全件をローカル/Turso へ
  python scripts/import_museums.py --max-per-facility 250   # 施設あたり最大250件（デモ向け・軽量）
  python scripts/import_museums.py --reset         # 既存の企業ミュージアムを消してから取り込み
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.review_csv import ParsedReview  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "museums" / "reviews.csv.gz"
CATEGORY = "企業ミュージアム"
TARGET = "容器文化ミュージアム"


def _review_id(place: str, reviewer: str, date: str, text: str) -> str:
    raw = f"{place}|{reviewer}|{date}|{text}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:16]


def _to_reviews(rows: pd.DataFrame) -> list[ParsedReview]:
    out, seen = [], set()
    for _, r in rows.iterrows():
        place = str(r["place_name"]).strip()
        reviewer = str(r.get("reviewer_name") or "").strip()
        date = str(r.get("review_date") or "")[:10]
        text = str(r.get("review_text") or "").strip()
        rid = _review_id(place, reviewer, date, text)
        if rid in seen:      # 完全重複行はスキップ（同一施設内で一意）
            continue
        seen.add(rid)
        rating = r.get("review_rating")
        rating = int(rating) if pd.notna(rating) else None
        out.append(ParsedReview(
            review_id=rid,
            rating=rating,
            text=text,
            review_date=date,
            reviewer_name=reviewer,
            local_guide=False,
            likes=None,
            owner_response="",
            owner_response_date="",
            subscores=[],
        ))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-facility", type=int, default=200,
                    help="比較施設あたりの最大取り込み件数（既定200・デモを軽く保つ）。"
                         "0 で全件取り込み。対象施設(容器文化ミュージアム)は常に全件。")
    ap.add_argument("--reset", action="store_true",
                    help="取り込み前に既存の企業ミュージアム施設を削除する")
    args = ap.parse_args()

    if not DATA.exists():
        sys.exit(f"データが見つかりません: {DATA}")

    df = pd.read_csv(DATA, compression="gzip")
    df["place_name"] = df["place_name"].astype(str).str.strip()
    facilities = sorted(df["place_name"].dropna().unique())
    print(f"読み込み: {len(df):,} 件 / {len(facilities)} 施設")

    conn = db.get_conn()
    db.init_db(conn)
    backend = "Turso" if hasattr(conn, "execute_pipeline") else "ローカルSQLite"
    print(f"接続先: {backend}")

    if args.reset:
        n = 0
        for name in facilities + [TARGET]:
            row = conn.execute("SELECT id FROM facility WHERE name = ?", (name,)).fetchone()
            if row:
                db.delete_facility(conn, row["id"])
                n += 1
        print(f"リセット: 既存 {n} 施設を削除")

    total_ins = total_skip = 0
    for i, name in enumerate(facilities, 1):
        sub = df[df["place_name"] == name]
        if args.max_per_facility and name != TARGET and len(sub) > args.max_per_facility:
            sub = sub.head(args.max_per_facility)

        reviews = _to_reviews(sub)
        avg = round(float(sub["review_rating"].dropna().mean()), 2) if sub["review_rating"].notna().any() else None
        ftype = "target" if name == TARGET else "comparison"

        fid = db.upsert_facility(
            conn, name, ftype=ftype, category=CATEGORY,
            general_rating=avg, total_reviews=len(reviews),
        )
        ins, skip = db.insert_reviews(conn, fid, reviews)
        total_ins += ins
        total_skip += skip
        tag = "★対象" if name == TARGET else ""
        print(f"  [{i:2d}/{len(facilities)}] {name[:28]:<28} {len(reviews):>4}件 "
              f"(新規{ins}/重複{skip}) {tag}")

    print(f"\n✅ 完了: 新規 {total_ins:,} 件 / 重複スキップ {total_skip:,} 件 / category=「{CATEGORY}」")
    print(f"   対象施設 = 「{TARGET}」(ftype=target)、他 {len(facilities)-1} 施設 = 比較施設")


if __name__ == "__main__":
    main()
