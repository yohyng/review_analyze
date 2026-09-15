"""Google Places を何回叩いたかを、アプリ側で数える。

**Google 側に「今月いくら使ったか」を安く聞く口は無い**（請求は Cloud
コンソール側にしか出ない）。KAIZODE の取得枠と同じで、数えられるのは
呼んだ本人だけなので、ここで帳簿を付ける。

数えるのは**呼び出し回数と、その種類**。金額ではない。
Places は 2025年3月から SKU 階層（Essentials / Pro / Enterprise）ごとに
単価と無料枠が分かれていて、どのフィールドがどの階層かは
FieldMask で決まる。階層の対応は Google の料金表が正なので、
ここでは「うちがどの形で何回呼んだか」までを持ち、
**金額の断定はしない**（画面にもそう書く）。

無料枠を使い切ったあとに気づく、を避けるのが目的。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def current_month(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def add(conn, kind: str, n: int = 1, month: Optional[str] = None) -> None:
    """呼び出しを1回ぶん記録する。**失敗しても黙って諦める**。

    帳簿のために写真の表示や検索を止めては本末転倒なので、例外は出さない。
    """
    if not kind or n <= 0:
        return
    month = month or current_month()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn.execute(
            "INSERT INTO places_usage(month, kind, calls, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(month, kind) DO UPDATE SET "
            "calls = calls + excluded.calls, updated_at = excluded.updated_at",
            (month, kind, int(n), ts),
        )
        conn.commit()
    except Exception:
        pass


def usage(conn, month: Optional[str] = None) -> dict:
    """{kind: calls}。読めなければ空。"""
    month = month or current_month()
    try:
        rows = conn.execute(
            "SELECT kind, calls FROM places_usage WHERE month = ?", (month,)
        ).fetchall()
    except Exception:
        return {}
    return {r[0]: int(r[1] or 0) for r in rows}


def months(conn, limit: int = 6) -> list[str]:
    """記録のある月を新しい順に。"""
    try:
        rows = conn.execute(
            "SELECT DISTINCT month FROM places_usage ORDER BY month DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    except Exception:
        return []
    return [r[0] for r in rows]


def total(conn, month: Optional[str] = None) -> int:
    return sum(usage(conn, month).values())


def install(conn) -> None:
    """places 側の記録フックに、このDBへの書き込みを繋ぐ。

    places.py に DB を持ち込まないための回り道。アプリの起動時に1回呼ぶ。
    """
    from . import places  # noqa: PLC0415

    places.set_recorder(lambda kind: add(conn, kind))
