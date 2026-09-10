"""施設ごとに「どれだけ拾えているか」を並べる。

3つの数を突き合わせる:

    ① Google マップ上の総口コミ数   … 母数。実際に何件あるのか
    ② KAIZODE が返せる件数          … そのうち収集できている量
    ③ 分析に使えた件数              … さらに日本語・本文ありで絞ったあと

①→② が KAIZODE の収集率、②→③ が本ツールの選別率。
どちらで落ちているのかを分けて見るためのもの。

■ ①の出どころは2つ
  (a) KAIZODE の `overall_place_reviews`（CSV取り込み時に facility.total_reviews
      へ保存済み）。追加の通信も課金も無い。
  (b) Google Places の userRatingCount。確実だが、**保存してはいけない**
      （規約上、無期限に保存してよいのは place_id だけ）。表示のたびに取る。

  そのため coverage は「保存済みの(a)」と「その場で引いた(b)」を分けて持つ。
  履歴として残せるのは (a) と ②③ だけ。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Coverage:
    facility: str

    # ① 母数
    google_total: Optional[int] = None      # Google 上の総口コミ数
    google_source: str = ""                 # "kaizode" | "places" | ""

    # ② KAIZODE が返せる件数
    kaizode_total: Optional[int] = None

    # ③ 手元の数
    db_total: int = 0                       # DBに入っている件数
    usable: int = 0                         # 観点判定に使えた件数

    note: str = ""                          # 取れなかった理由など

    # ── 率 ─────────────────────────────────────────────────────────
    @staticmethod
    def _rate(num: Optional[int], den: Optional[int]) -> Optional[float]:
        if not den or num is None:
            return None
        return num / den

    @property
    def collect_rate(self) -> Optional[float]:
        """KAIZODE の収集率（② ÷ ①）。"""
        return self._rate(self.kaizode_total, self.google_total)

    @property
    def import_rate(self) -> Optional[float]:
        """取り込み率（DB ÷ ②）。"""
        return self._rate(self.db_total, self.kaizode_total)

    @property
    def usable_rate(self) -> Optional[float]:
        """分析に使えた率（③ ÷ ①）。最終的にどれだけ届いたか。"""
        return self._rate(self.usable, self.google_total)

    @property
    def missing(self) -> Optional[int]:
        """Google にあるのに KAIZODE から取れていない件数。"""
        if self.google_total is None or self.kaizode_total is None:
            return None
        return max(0, self.google_total - self.kaizode_total)


def _stored_google_total(conn, name: str) -> Optional[int]:
    """CSV取り込み時に保存された総口コミ数（KAIZODE 由来）。"""
    row = conn.execute(
        "SELECT total_reviews FROM facility WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        return None
    v = row["total_reviews"] if not isinstance(row, tuple) else row[0]
    return int(v) if v is not None else None


def _db_total(conn, name: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM review r JOIN facility f ON f.id = r.facility_id "
        "WHERE f.name = ?", (name,)
    ).fetchone()
    return int(row[0]) if row else 0


def assess(
    conn,
    facility_name: str,
    *,
    kaizode_client=None,
    dataset_id: Optional[str] = None,
    places_key: str = "",
) -> Coverage:
    """1施設ぶんの内訳。通信できないものは None のままにする。

    kaizode_client を渡すと ② を問い合わせる（1件ぶん引く＝呼び出し側で
    帳簿に付けること）。places_key を渡すと ① を Google から取り直す。
    どちらも省略すれば、保存済みの数字だけで組み立てる。
    """
    from . import reliability  # noqa: PLC0415

    cov = Coverage(facility=facility_name)
    cov.db_total = _db_total(conn, facility_name)
    cov.usable = reliability.funnel(conn, facility_name).usable

    # ① まず保存済み（KAIZODE 由来・無料）
    stored = _stored_google_total(conn, facility_name)
    if stored is not None:
        cov.google_total = stored
        cov.google_source = "kaizode"

    # ① 取れていなければ Google に聞く（保存はしない）
    if cov.google_total is None and places_key:
        try:
            from . import places  # noqa: PLC0415

            d = places.details_for_facility(conn, facility_name, places_key)
            if d.review_count is not None:
                cov.google_total = d.review_count
                cov.google_source = "places"
        except Exception as e:      # 取れなくても他の数字は返す
            cov.note = f"Google からの総数取得に失敗: {type(e).__name__}"

    # ② KAIZODE が返せる件数
    if kaizode_client is not None and dataset_id:
        try:
            cov.kaizode_total = kaizode_client.count_reviews(dataset_id)
        except Exception as e:
            cov.note = (cov.note + " / " if cov.note else "") + \
                f"KAIZODE への問い合わせに失敗: {type(e).__name__}"

    return cov


def summarize(rows: list) -> dict:
    """複数施設ぶんをまとめる。分からないものは母数から外す。"""
    known = [c for c in rows if c.google_total]
    g = sum(c.google_total for c in known)
    k = sum(c.kaizode_total or 0 for c in known)
    u = sum(c.usable for c in known)
    return {
        "facilities": len(rows),
        "with_total": len(known),
        "google_total": g,
        "kaizode_total": k,
        "usable": u,
        "collect_rate": (k / g) if g else None,
        "usable_rate": (u / g) if g else None,
    }
