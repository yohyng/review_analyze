"""分析の事前計算を、途中で止まっても続きからやれる形で回す。

なぜ分割するか:
  全施設を1回のスクリプト実行でやり切る造りだと、
  - Streamlit Cloud の実行時間・WebSocket が先に切れると全部やり直し
  - 形態素解析の結果を最後にまとめて書いていたので、落ちるとそこまでの
    解析がまるごと消える（一番重い処理なのに）
  - Turso が1回 502 を返すだけで全体が落ちる
  という三重の壊れ方をする。

  なので「1バッチ = 数施設」に切り、**バッチごとに必ず書き切る**。
  次に走らせるときは、まだ計算していない施設だけが残っている。
  何度押しても・途中で閉じても、進んだぶんは必ず残る。

Streamlit に依存しないので、そのままテストから呼べる。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import db, text_analysis, topic_score

# 1バッチあたりの施設数の既定。1施設あたり数百件の口コミを形態素解析するので、
# ここを大きくすると1回の実行が長くなり、途中で切られる危険が増える。
DEFAULT_BATCH = 5


@dataclass
class Todo:
    """まだ事前計算していない施設。"""
    name: str
    facility_id: int
    n_reviews: int


@dataclass
class BatchResult:
    computed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)      # 本文が無い等
    failed: list[tuple[str, str]] = field(default_factory=list)  # (施設名, 理由)
    tokens_saved: int = 0
    scores_saved: int = 0                                 # 実際にDBへ書けた施設数

    @property
    def n_done(self) -> int:
        return len(self.computed) + len(self.skipped)

    @property
    def advanced(self) -> bool:
        """このバッチで「残り」が実際に減ったか。

        計算できたかではなく **DBに書けたか** で判定する。
        キャッシュの書き込みは失敗しても分析を止めない設計なので、
        書けていないのに「進んだ」と扱うと、呼び出し側の自動継続が
        同じ施設を永久に計算し直す（実際にそうなった）。
        """
        if self.computed:
            return self.scores_saved > 0
        return bool(self.skipped)


def survey(conn) -> tuple[list[Todo], int]:
    """(未計算の施設, 口コミがある施設の総数) を返す。

    施設ごとに問い合わせず、施設一覧とキャッシュをそれぞれ1クエリで読んで
    突き合わせる（Turso は 1クエリ = 1 HTTP 往復なので、施設数ぶん撃たない）。
    """
    rows = conn.execute(
        "SELECT f.id AS id, f.name AS name, COUNT(r.id) AS nr "
        "FROM facility f JOIN review r ON r.facility_id = f.id "
        "GROUP BY f.id, f.name ORDER BY f.name"
    ).fetchall()
    cached = db.get_topic_score_cache_bulk(conn)
    todo = [
        Todo(name=r["name"], facility_id=r["id"], n_reviews=r["nr"])
        for r in rows
        if (r["id"], r["nr"]) not in cached
    ]
    return todo, len(rows)


def _topics_json(result) -> str:
    return json.dumps([
        {"name": t.name, "weight": t.weight, "avg_score": t.avg_score,
         "total_score": t.total_score, "salience": t.salience,
         "sentiment": t.sentiment}
        for t in result.topics
    ])


def run_batch(conn, batch: list[Todo], *, on_progress=None) -> BatchResult:
    """1バッチぶんを計算して、**必ず**書き切ってから返す。

    - 本文は1クエリでまとめて読む
    - 1施設が転んでも残りは続ける（理由を failed に残す）
    - 形態素解析キャッシュはこのバッチの終わりに必ず書き出す
      （最後にまとめて書くと、途中で落ちたとき一番重い処理が丸ごと消える）
    """
    res = BatchResult()
    if not batch:
        return res

    texts_by_fac = db.review_texts_by_facility(conn, [t.name for t in batch])

    pending: list[tuple] = []
    for i, item in enumerate(batch, 1):
        if on_progress:
            on_progress(i, len(batch), item.name)
        try:
            texts = texts_by_fac.get(item.name) or []
            scored = topic_score.analyze_reviews(texts)
            if scored.empty:
                res.skipped.append(item.name)
                continue
            pending.append((
                item.facility_id, item.n_reviews, _topics_json(scored),
                scored.overall_score, scored.n_sentences,
            ))
            res.computed.append(item.name)
        except Exception as exc:                      # noqa: BLE001
            res.failed.append((item.name, f"{type(exc).__name__}: {exc}"))

    # ここまでの成果を書き切る。以降で落ちても、このバッチは残る。
    res.scores_saved = db.set_topic_score_cache_bulk(conn, pending)
    res.tokens_saved = text_analysis.flush_token_cache(conn)
    if pending and not res.scores_saved:
        # 書けていないことを黙って握りつぶさない。呼び出し側はこれを見て
        # 自動継続を止める（でないと同じ施設を無限に計算し続ける）。
        res.failed.append(("(DBへの保存)", "感情スコアのキャッシュを書き込めませんでした"))
    return res


def next_batch(todo: list[Todo], size: int = DEFAULT_BATCH) -> list[Todo]:
    return todo[:max(1, int(size))]
