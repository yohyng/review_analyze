"""施設名 → 住所（OpenStreetMap / Nominatim）。

デプロイ先で外向き通信が可能なら住所を自動取得する。取得できない環境
（通信ブロック・レート制限・該当なし）では None を返し、呼び出し側は
手入力にフォールバックする。Nominatim の利用規約に沿って User-Agent を
付け、結果は lru_cache でメモ化（同一施設は1回だけ問い合わせ）。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

NOMINATIM = "https://nominatim.openstreetmap.org/search"
_UA = "VoiceBAUM/0.7 (facility review analysis; contact: admin@example.com)"


@lru_cache(maxsize=512)
def lookup(name: str, hint: str = "") -> Optional[dict]:
    """施設名（＋任意のヒント地名）→ {address, lat, lon, category} or None。"""
    if not name or not name.strip():
        return None
    try:
        import requests
    except Exception:
        return None

    query = f"{name} {hint}".strip()
    try:
        resp = requests.get(
            NOMINATIM,
            params={
                "q": query, "format": "jsonv2", "limit": 1,
                "accept-language": "ja", "addressdetails": 1,
            },
            headers={"User-Agent": _UA},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    if not data:
        return None
    top = data[0]
    return {
        "address": top.get("display_name") or "",
        "lat": top.get("lat"),
        "lon": top.get("lon"),
        "category": top.get("type") or top.get("category") or "",
    }
