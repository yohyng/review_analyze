"""KAIZODE v2 API クライアント（口コミ収集サービスからのレビュー取得）。

仕様: kaizode-openapi.json（OpenAPI 3.1）
  * ベースURL   : https://kaizode-v2.scorobo.ai/api/v1
  * 認証        : リクエストヘッダ `x-api-key`
  * レート制限  : 20リクエスト/分（超過429）→ 既定3.2秒スロットル＋429リトライ
  * サイズ上限  : レスポンス30MB（超過413）→ limit を控えめにしてページネーション

使い方:
    client = KaizodeClient()                       # KAIZODE_API_KEY 環境変数から
    for ds in client.list_datasets(): ...
    for rv in client.iter_reviews(dataset_id, published_since="2025-01-01"): ...

このモジュールは通信部分と「KAIZODE Review → ParsedReview」変換、
および差分取得のための同期状態（kaizode_sync テーブル）ヘルパーを提供する。
"""
from __future__ import annotations

import itertools
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Iterator, Optional

from .review_csv import ParsedReview

DEFAULT_BASE_URL = "https://kaizode-v2.scorobo.ai/api/v1"

# KAIZODE から新規に取得するレビューの月間上限（コスト/枠の保護）。
#
# 実効値は DB の app_setting（キー SETTING_MONTHLY_LIMIT）から読む。
# 管理画面から変えられ、デプロイし直しても消えない。未設定ならこの既定値。
DEFAULT_MONTHLY_LIMIT = 10_000
SETTING_MONTHLY_LIMIT = "kaizode_monthly_limit"

# 上限として受け付ける範囲。0 にすると新規取得を止められる。
MONTHLY_LIMIT_MIN = 0
MONTHLY_LIMIT_MAX = 1_000_000

# 後方互換（旧コードが参照している既定値）。実際の判定には使わないこと。
MONTHLY_LIMIT = DEFAULT_MONTHLY_LIMIT


def maps_search_url(name: str) -> str:
    """施設名から Googleマップ検索URLを生成する。

    KAIZODE はURL指定で収集を発注する仕様のため、施設名だけで発注したいときに
    名前を検索クエリに変換して渡す。検索ベースなので同名施設があると取り違える
    可能性がある点に注意（正確に指定したいときは実際の場所URLを使う）。
    """
    q = urllib.parse.quote((name or "").strip())
    return f"https://www.google.com/maps/search/?api=1&query={q}"

STATUS_LABELS = {
    10: "レビュー抽出中",
    20: "解析実行中",
    30: "解析完了",
    40: "レビュー抽出失敗",
}
STATUS_DONE = 30

# 30MB上限対策: 1回のDL件数は控えめに（30,000がAPI上限だがペイロードが太る）
DEFAULT_PAGE_LIMIT = 5000


class KaizodeError(RuntimeError):
    pass


class KaizodeClient:
    """最小限の同期クライアント。20req/分制限に合わせてスロットルする。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        session=None,
        min_interval: float = 3.2,   # ~18req/分
        max_retries: int = 3,
    ):
        self.api_key = (api_key or os.environ.get("KAIZODE_API_KEY", "")).strip()
        if not self.api_key:
            raise KaizodeError(
                "KAIZODE_API_KEY が未設定です（環境変数 or KaizodeClient(api_key=...)）"
            )
        # HTTPヘッダ(x-api-key)は latin-1 のみ。日本語などが混じると requests が
        # UnicodeEncodeError で落ちる → ここで分かりやすいエラーにする（プレースホルダ
        # 文字列を貼ってしまった等をここで検出）。
        try:
            self.api_key.encode("latin-1")
        except UnicodeEncodeError:
            raise KaizodeError(
                "APIキーに使えない文字（日本語など）が含まれています。"
                "KAIZODEの正しいAPIキー（半角英数字）を設定してください"
                "（プレースホルダ文字列が残っていないか確認）。"
            )
        self.base_url = base_url.rstrip("/")
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request_at = 0.0

    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _request(self, method: str, path: str, *, params=None, json=None) -> dict:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            self._throttle()
            resp = self._session.request(
                method, url,
                headers={"x-api-key": self.api_key},
                params=params, json=json, timeout=60,
            )
            self._last_request_at = time.monotonic()
            if resp.status_code == 429 and attempt < self.max_retries:
                time.sleep(65)          # 1分窓が明けるまで待って再試行
                continue
            if resp.status_code >= 400:
                try:
                    msg = resp.json().get("message", "")
                except Exception:
                    msg = resp.text[:200]
                raise KaizodeError(f"KAIZODE {resp.status_code}: {msg} ({method} {path})")
            if resp.status_code == 204:
                return {}
            return resp.json()
        raise KaizodeError(f"KAIZODE 429: リトライ上限に到達 ({method} {path})")

    # ------------------------------------------------------------------ #
    # データセット
    # ------------------------------------------------------------------ #
    def list_datasets(self) -> list[dict]:
        return self._request("GET", "/datasets").get("data", [])

    def get_dataset(self, dataset_id: str) -> dict:
        return self._request("GET", f"/datasets/{dataset_id}").get("data", {})

    def create_dataset(self, dataset_name: str, urls: list[dict]) -> dict:
        """urls: [{"url": ..., "since": "YYYY-MM-DD"|None, "review_target_name": 施設名}]"""
        return self._request(
            "POST", "/datasets",
            json={"dataset_name": dataset_name, "urls": urls},
        ).get("data", {})

    def rerun_dataset(self, dataset_id: str, urls: Optional[list[dict]] = None) -> dict:
        body = {"urls": urls} if urls else None
        return self._request("POST", f"/datasets/{dataset_id}/rerun", json=body).get("data", {})

    # ------------------------------------------------------------------ #
    # レビュー（ページネーション＋差分取得）
    # ------------------------------------------------------------------ #
    def iter_reviews(
        self,
        dataset_id: str,
        published_since: Optional[str] = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> Iterator[dict]:
        page = 0
        while True:
            params = {"limit": limit, "page": page}
            if published_since:
                params["published_since"] = published_since
            body = self._request("GET", f"/datasets/{dataset_id}/reviews", params=params)
            data = body.get("data", [])
            yield from data
            total = (body.get("pagination") or {}).get("total_items")
            page += 1
            if len(data) < limit:
                break
            if total is not None and page * limit >= total:
                break


# ---------------------------------------------------------------------- #
# KAIZODE Review → ParsedReview（DB取り込み形式）
# ---------------------------------------------------------------------- #
def to_parsed_review(r: dict) -> ParsedReview:
    title = (r.get("review_title") or "").strip()
    body = (r.get("review") or "").strip()
    text = f"{title}\n{body}".strip() if title else body

    rating = r.get("review_rating")
    if rating is not None:
        rating = float(rating)
        if rating.is_integer():
            rating = int(rating)

    published = (r.get("published_at") or "")[:19]

    return ParsedReview(
        review_id=str(r.get("review_id") or ""),
        rating=rating,
        text=text,
        review_date=published,
        reviewer_name=(r.get("publisher_name") or "").strip(),
        local_guide=False,
        likes=None,
        owner_response="",
        owner_response_date="",
        subscores=[],
    )


def facility_name_of(r: dict, fallback: str = "不明") -> str:
    return (r.get("review_target_name") or r.get("dataset_name") or fallback).strip()


def match_datasets(datasets: list[dict], query: str) -> list[dict]:
    """データセット名に query が部分一致するものを返す（発注前のプレビュー用）。

    KAIZODE には施設名検索APIが無く、データセットの中身（対象施設）はURL単位で
    しか分からないため、**データセット名**での緩いマッチに留まる（KAIZODE発注時に
    施設名をデータセット名として渡す運用を前提）。各要素に status_label を付与。
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for ds in datasets:
        name = (ds.get("dataset_name") or "")
        if q in name.lower():
            item = dict(ds)
            item["status_label"] = STATUS_LABELS.get(ds.get("status"), str(ds.get("status")))
            out.append(item)
    return out


# ---------------------------------------------------------------------- #
# 同期の本体（CLI と 管理画面の両方から使う）
# ---------------------------------------------------------------------- #
def sync_datasets(
    client: "KaizodeClient",
    conn,
    *,
    category: Optional[str] = None,
    ftype: str = "comparison",
    dataset_id: Optional[str] = None,
    full: bool = False,
    limit: int = DEFAULT_PAGE_LIMIT,
    log=print,
) -> dict:
    """解析完了(status=30)のデータセットからレビューを差分取得し、DBへ取り込む。

    月間取得上限（monthly_limit(conn)）を超えないよう、当月の残枠までで打ち切る。上限で
    途中停止したデータセットは last_sync を進めない（枠回復後に続きから取得）。

    Returns {"inserted","skipped_dup","datasets_synced","datasets_skipped",
             "fetched","limit_reached","monthly_used","monthly_limit"}.
    """
    from . import db as _db

    month = current_month()
    limit_n = monthly_limit(conn)          # 判定はDBの設定値で行う
    remaining = monthly_remaining(conn, month, limit_n)
    if remaining <= 0:
        used = get_monthly_usage(conn, month)
        log(f"⚠️ 今月のKAIZODE取得上限（{limit_n:,}件）に達しています。"
            f"翌月まで新規取得はできません（今月 {used:,} 件）。")
        return {"inserted": 0, "skipped_dup": 0, "datasets_synced": 0,
                "datasets_skipped": 0, "fetched": 0, "limit_reached": True,
                "monthly_used": used, "monthly_limit": limit_n}

    datasets = client.list_datasets()
    if dataset_id:
        datasets = [d for d in datasets if d.get("dataset_id") == dataset_id]
        if not datasets:
            raise KaizodeError(f"データセットが見つかりません: {dataset_id}")

    total_ins = total_skip = synced = skipped = 0
    fetched = 0
    limit_reached = False
    for ds in datasets:
        dsid = ds.get("dataset_id")
        name = ds.get("dataset_name", "")
        status = ds.get("status")
        if status != STATUS_DONE:
            log(f"⏭️ {name}: {STATUS_LABELS.get(status, status)} のためスキップ")
            skipped += 1
            continue

        budget = remaining - fetched
        if budget <= 0:
            log(f"⚠️ 今月の上限（{limit_n:,}件）に達したため、以降をスキップしました。")
            limit_reached = True
            break

        since = None if full else get_last_sync(conn, dsid)
        log(f"⬇️ {name}: {'全件' if since is None else f'差分（{since} 以降）'}を取得中…")
        # 残枠までしか取らない（islice でページ取得も途中で止まる＝枠を消費しすぎない）。
        # budget+1件目まで覗くことで「ちょうど残枠と同数だった（＝実際は全件取得できた）」
        # ケースを「打ち切られた」と誤判定しないようにする（境界値バグ対策）。
        _batch = list(itertools.islice(
            client.iter_reviews(dsid, published_since=since, limit=limit), budget + 1))
        truncated = len(_batch) > budget        # budget+1件目が実在＝本当に打ち切られた
        reviews = _batch[:budget]
        fetched += len(reviews)

        # **取得した直後に帳簿へ付ける。**
        # 以前は関数の最後で fetched をまとめて加算していたので、途中で
        # 例外（ネットワーク断・Turso の 502・取り込み失敗）が出ると、
        # すでにKAIZODEから引いた件数が帳簿に一切残らなかった。
        # 契約枠は「引いた時点」で消費されるので、帳簿もそこで進めないと
        # 実使用が上限を超える。DBに取り込めたかどうかとは別の話。
        if reviews:
            add_monthly_usage(conn, len(reviews), month)

        if not reviews:
            log("　　新着なし")
            set_last_sync(conn, dsid, name, since)
            synced += 1
            continue

        by_fac: dict[str, list] = {}
        for r in reviews:
            by_fac.setdefault(facility_name_of(r, fallback=name), []).append(r)

        for fac_name, revs in sorted(by_fac.items()):
            fid = _db.upsert_facility(conn, fac_name, ftype=ftype, category=category)
            ins, skip = _db.insert_reviews(
                conn, fid, [to_parsed_review(r) for r in revs]
            )
            total_ins += ins
            total_skip += skip
            log(f"　　{fac_name}: {len(revs)}件 (新規{ins}/重複{skip})")

        if truncated:
            # 上限で途中まで取得 → last_sync は進めない（次回同じ since から続きを取得）
            log("　　⚠️ 今月の上限に達したため途中で停止（続きは翌月/枠回復後に取得）")
            return {"inserted": total_ins, "skipped_dup": total_skip,
                    "datasets_synced": synced, "datasets_skipped": skipped,
                    "fetched": fetched, "limit_reached": True,
                    "monthly_used": get_monthly_usage(conn, month),
                    "monthly_limit": limit_n}

        last_pub = max((r.get("published_at") or "") for r in reviews)[:19] or since
        set_last_sync(conn, dsid, name, last_pub)
        synced += 1

    used = get_monthly_usage(conn, month)   # 加算は取得の直後に済ませている
    return {"inserted": total_ins, "skipped_dup": total_skip,
            "datasets_synced": synced, "datasets_skipped": skipped,
            "fetched": fetched, "limit_reached": limit_reached,
            "monthly_used": used, "monthly_limit": limit_n}


# ---------------------------------------------------------------------- #
# 同期状態（差分取得のための published_since 記録）— kaizode_sync テーブル
# ---------------------------------------------------------------------- #
def get_last_sync(conn, dataset_id: str) -> Optional[str]:
    row = conn.execute(
        "SELECT last_published_at FROM kaizode_sync WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    return row[0] if row else None


def set_last_sync(conn, dataset_id: str, dataset_name: str, last_published_at: Optional[str]) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # DELETE → INSERT の2文にすると、Turso では間に失敗の窓が開く
    # （1文=1往復・トランザクション無し）。行が消えると次回は since=None に
    # なって**全件を再ダウンロード**し、新規0件のまま月枠だけを焼く。
    # 1文の冪等な UPSERT にすれば窓が消え、往復も2→1に減る。
    conn.execute(
        "INSERT OR REPLACE INTO kaizode_sync"
        "(dataset_id, dataset_name, last_published_at, synced_at) "
        "VALUES (?, ?, ?, ?)",
        (dataset_id, dataset_name, last_published_at, ts),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# 月間取得上限（kaizode_usage テーブル）
# --------------------------------------------------------------------------- #
def current_month(now: Optional[datetime] = None) -> str:
    """当月キー 'YYYY-MM'（UTC基準）。"""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def get_monthly_usage(conn, month: Optional[str] = None) -> int:
    """当月にKAIZODEから取得したレビュー件数。"""
    month = month or current_month()
    row = conn.execute(
        "SELECT downloaded FROM kaizode_usage WHERE month = ?", (month,)
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def add_monthly_usage(conn, n: int, month: Optional[str] = None) -> int:
    """当月の取得件数に n を加算し、加算後の合計を返す。"""
    if n <= 0:
        return get_monthly_usage(conn, month)
    month = month or current_month()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO kaizode_usage(month, downloaded, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(month) DO UPDATE SET downloaded = downloaded + excluded.downloaded, "
        "updated_at = excluded.updated_at",
        (month, int(n), ts),
    )
    conn.commit()
    return get_monthly_usage(conn, month)


def monthly_limit(conn) -> int:
    """当月の新規取得上限。DBの設定を優先し、無ければ既定値。

    毎回DBを引くのは、管理画面で変えた直後から効かせたいため
    （プロセスを再起動しないと反映されない、という事故を避ける）。
    """
    from . import db as _db  # noqa: PLC0415

    n = _db.get_setting_int(conn, SETTING_MONTHLY_LIMIT, DEFAULT_MONTHLY_LIMIT)
    return max(MONTHLY_LIMIT_MIN, min(MONTHLY_LIMIT_MAX, int(n)))


def set_monthly_limit(conn, n: int) -> int:
    """上限を保存して、保存後の値を返す。範囲外は丸める。"""
    from . import db as _db  # noqa: PLC0415

    n = max(MONTHLY_LIMIT_MIN, min(MONTHLY_LIMIT_MAX, int(n)))
    _db.set_setting(conn, SETTING_MONTHLY_LIMIT, n)
    return n


def monthly_remaining(conn, month: Optional[str] = None,
                      limit: Optional[int] = None) -> int:
    """当月の残枠（0未満にはならない）。limit 未指定なら設定値を使う。"""
    if limit is None:
        limit = monthly_limit(conn)
    return max(0, limit - get_monthly_usage(conn, month))
