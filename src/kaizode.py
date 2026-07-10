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

import os
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

from .review_csv import ParsedReview

DEFAULT_BASE_URL = "https://kaizode-v2.scorobo.ai/api/v1"

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
        self.api_key = api_key or os.environ.get("KAIZODE_API_KEY", "")
        if not self.api_key:
            raise KaizodeError(
                "KAIZODE_API_KEY が未設定です（環境変数 or KaizodeClient(api_key=...)）"
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
    conn.execute("DELETE FROM kaizode_sync WHERE dataset_id = ?", (dataset_id,))
    conn.execute(
        "INSERT INTO kaizode_sync(dataset_id, dataset_name, last_published_at, synced_at) "
        "VALUES (?, ?, ?, ?)",
        (dataset_id, dataset_name, last_published_at, ts),
    )
    conn.commit()
