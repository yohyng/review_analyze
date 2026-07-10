#!/usr/bin/env python3
"""KAIZODE から口コミ対象施設のレビューを取得して DB（Turso/SQLite）へ取り込む。

画面を閉じていても動く定期ジョブ（GitHub Actions 等）から実行する想定。
KAIZODE 側が収集を非同期で行うため、本スクリプトは軽い:

  ジョブA（発注）  : --create facilities.csv   … データセット作成→収集開始
  ジョブB（回収）  : --sync                     … 解析完了(status=30)分を差分DL→DB挿入
  状態確認        : --status                   … データセット一覧と収集状況

必要な環境変数:
  KAIZODE_API_KEY               … KAIZODE 画面の「APIキー表示」から
  TURSO_URL / TURSO_TOKEN       … 省略時はローカル data/reviews.db

facilities.csv の形式（ヘッダ必須）:
  name,url,since
  容器文化ミュージアム,https://www.google.com/maps/...,2024-01-01
  （since は省略可）

使い方例:
  python scripts/fetch_kaizode.py --status
  python scripts/fetch_kaizode.py --create data/kaizode/facilities.csv --dataset-name 口コミ対象2026
  python scripts/fetch_kaizode.py --sync --category 企業ミュージアム
  python scripts/fetch_kaizode.py --sync --dataset-id XXXX --full   # 差分でなく全件取り直し
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, kaizode  # noqa: E402


def cmd_status(client: kaizode.KaizodeClient) -> None:
    datasets = client.list_datasets()
    if not datasets:
        print("データセットがありません。--create で作成してください。")
        return
    print(f"{len(datasets)} 件のデータセット:")
    for ds in datasets:
        label = kaizode.STATUS_LABELS.get(ds.get("status"), f"status={ds.get('status')}")
        sched = " [定期]" if ds.get("is_scheduled") else ""
        print(f"  {ds.get('dataset_id')}  {ds.get('dataset_name','')!s:<24} {label}{sched}"
              f"  updated={ds.get('updated_at','')}")


def cmd_create(client: kaizode.KaizodeClient, csv_path: str, dataset_name: str) -> None:
    urls = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            item = {"url": url,
                    "review_target_name": (row.get("name") or "").strip() or None}
            since = (row.get("since") or "").strip()
            if since:
                item["since"] = since
            urls.append(item)
    if not urls:
        sys.exit(f"URLが1件も読めませんでした: {csv_path}（ヘッダ name,url,since が必要）")

    print(f"{len(urls)} 施設でデータセット「{dataset_name}」を作成します…")
    ds = client.create_dataset(dataset_name, urls)
    label = kaizode.STATUS_LABELS.get(ds.get("status"), ds.get("status"))
    print(f"✅ 作成: dataset_id={ds.get('dataset_id')} 状態={label}")
    print("   収集はKAIZODE側で非同期に進みます。完了後に --sync で取り込んでください。")


def cmd_sync(client: kaizode.KaizodeClient, args) -> None:
    conn = db.get_conn()
    db.init_db(conn)
    backend = "Turso" if hasattr(conn, "execute_pipeline") else "ローカルSQLite"
    print(f"DB接続先: {backend}")

    try:
        res = kaizode.sync_datasets(
            client, conn,
            category=args.category, ftype=args.ftype,
            dataset_id=args.dataset_id, full=args.full, limit=args.limit,
        )
    except kaizode.KaizodeError as e:
        sys.exit(f"❌ {e}")

    print(f"\n✅ 同期完了: 新規 {res['inserted']:,} 件 / 重複スキップ {res['skipped_dup']:,} 件"
          f"（{res['datasets_synced']} データセット / スキップ {res['datasets_skipped']}）")
    if res["inserted"]:
        print("   アプリを開くと新データで分析できます（トピック行列は自動で再計算）。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="データセット一覧と収集状況を表示")
    g.add_argument("--create", metavar="CSV", help="facilities.csv からデータセット作成（収集開始）")
    g.add_argument("--sync", action="store_true", help="解析完了分のレビューを差分取得してDBへ")
    ap.add_argument("--dataset-name", default="口コミ対象", help="--create 時のデータセット名")
    ap.add_argument("--dataset-id", help="--sync 対象を1データセットに絞る")
    ap.add_argument("--full", action="store_true", help="--sync で差分でなく全件取得")
    ap.add_argument("--limit", type=int, default=kaizode.DEFAULT_PAGE_LIMIT,
                    help="1リクエストあたりの取得件数（30MB上限対策）")
    ap.add_argument("--category", default=None, help="施設の category（例: 企業ミュージアム）")
    ap.add_argument("--ftype", default="comparison", choices=["target", "comparison"],
                    help="施設の種別（既定: comparison）")
    args = ap.parse_args()

    try:
        client = kaizode.KaizodeClient()
    except kaizode.KaizodeError as e:
        sys.exit(f"❌ {e}")

    if args.status:
        cmd_status(client)
    elif args.create:
        cmd_create(client, args.create, args.dataset_name)
    else:
        cmd_sync(client, args)


if __name__ == "__main__":
    main()
