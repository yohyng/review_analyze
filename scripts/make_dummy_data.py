#!/usr/bin/env python
"""ダミーデータを生成する CLI。中身は src/dummy_data.py。

    python scripts/make_dummy_data.py                 # data/dummy.db に生成
    python scripts/make_dummy_data.py --out path.db   # 出力先を指定
    python scripts/make_dummy_data.py --verify        # 生成して答え合わせ
    VOICEBAUM_DB=data/dummy.db streamlit run app.py   # ダミーDBでアプリ起動

アプリの管理画面「🧪 ダミーデータ」からも同じことができる。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, dummy_data  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/dummy.db")
    ap.add_argument("--verify", action="store_true", help="分析を回して答え合わせ")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"ダミーデータを生成: {out}")

    conn = db.get_conn(out)
    db.init_db(conn)
    dummy_data.build(conn, log=lambda m: print(f"  {m}"))

    total = sum(f["n"] for f in dummy_data.FACILITIES)
    print(f"\n{len(dummy_data.FACILITIES)}施設 / 口コミ {total}件")
    print(f"\nアプリで使う:\n    VOICEBAUM_DB={out} streamlit run app.py")

    if not args.verify:
        return 0

    print("\n分析中…")
    r = dummy_data.verify(conn)
    bar = "=" * 66
    print(f"\n{bar}\n答え合わせ: {r['target']}\n{bar}")
    print(f"較正: {r['calibrated']} / 順位 {r['rank']}/{r['total']} "
          f"/ 総合 {r['overall5']:.2f}")
    print(f"\n仕込んだ強み: {r['want_strong']}")
    print(f"検出した強みTOP5: {r['got_strong']}")
    print(f"  → 再現 {len(r['hit_strong'])}/{len(r['want_strong'])}: {r['hit_strong']}")
    print(f"\n仕込んだ弱み: {r['want_weak']}")
    print(f"検出した弱みTOP5: {r['got_weak']}")
    print(f"  → 再現 {len(r['hit_weak'])}/{len(r['want_weak'])}: {r['hit_weak']}")
    print(f"\n仕込んだ出来事: {r['event_month']} に評価を下げた")
    print(f"検出した変化点: {r['change_points']}")
    print(f"  → {'検出できた' if r['event_detected'] else '検出できず'}")
    print(f"\n{bar}\n判定: "
          f"{'OK — 仕込んだ特徴を再現できています' if r['ok'] else 'NG — 再現できていません'}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
