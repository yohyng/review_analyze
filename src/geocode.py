"""施設名 → PROFILE項目（住所・アクセス・開業・業種）を OpenStreetMap から機械的に補完。

LLM（生成）は使わず、構造化データのみを使う:
  * 住所 / 緯度経度 / 開業(start_date) / 業種  … Nominatim
  * アクセス（最寄り駅・徒歩分）               … Overpass（最寄りの railway=station）

取得できない環境（通信ブロック・レート制限・該当なし）では空を返し、
呼び出し側は手入力にフォールバックする。結果は lru_cache でメモ化。
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Optional

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
_UA = "VoiceBAUM/0.8 (facility review analysis; contact: admin@example.com)"

# OSM の type/class → 表示用の業種ラベル
_CATEGORY_MAP = {
    "museum": "美術館・博物館", "gallery": "ギャラリー", "artwork": "美術・展示",
    "attraction": "観光施設", "theme_park": "テーマパーク", "zoo": "動物園",
    "aquarium": "水族館", "library": "図書館", "adery": "醸造所",
    "viewpoint": "展望施設", "hotel": "ホテル", "restaurant": "レストラン",
    "cafe": "カフェ", "information": "案内施設",
}


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _year(val: str) -> Optional[str]:
    """'2015' / '2015-04-01' / 'C1998' などから西暦4桁を抽出。"""
    if not val:
        return None
    import re
    m = re.search(r"(1[6-9]\d\d|20\d\d)", str(val))
    return f"{m.group(1)}年" if m else None


@lru_cache(maxsize=512)
def _geocode(name: str, hint: str = "") -> Optional[dict]:
    if not name or not name.strip():
        return None
    try:
        import requests
    except Exception:
        return None
    try:
        resp = requests.get(
            NOMINATIM,
            params={"q": f"{name} {hint}".strip(), "format": "jsonv2", "limit": 1,
                    "accept-language": "ja", "addressdetails": 1, "extratags": 1},
            headers={"User-Agent": _UA}, timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not data:
        return None
    top = data[0]
    extra = top.get("extratags") or {}
    otype = top.get("type") or ""
    return {
        "address": top.get("display_name") or "",
        "lat": top.get("lat"),
        "lon": top.get("lon"),
        "open_year": _year(extra.get("start_date") or extra.get("opening_date") or ""),
        "category": _CATEGORY_MAP.get(otype) or _CATEGORY_MAP.get(top.get("category") or ""),
    }


@lru_cache(maxsize=512)
def _nearest_station(lat: float, lon: float) -> Optional[tuple]:
    """(駅名, 徒歩分) or None。Overpass で 2km 以内の最寄り railway=station。"""
    try:
        import requests
    except Exception:
        return None
    q = (f'[out:json][timeout:10];'
         f'(node["railway"="station"](around:2500,{lat},{lon});'
         f'node["railway"="halt"](around:2500,{lat},{lon}););out body;')
    try:
        resp = requests.post(OVERPASS, data={"data": q},
                             headers={"User-Agent": _UA}, timeout=12)
        resp.raise_for_status()
        els = resp.json().get("elements", [])
    except Exception:
        return None
    best = None
    for e in els:
        nm = (e.get("tags") or {}).get("name")
        if not nm or e.get("lat") is None:
            continue
        d = _haversine_m(lat, lon, e["lat"], e["lon"])
        if best is None or d < best[1]:
            best = (nm, d)
    if not best:
        return None
    name = best[0] if best[0].endswith("駅") else best[0] + "駅"
    walk_min = max(1, round(best[1] / 80))   # 80 m/分
    return (name, walk_min)


def lookup(name: str, hint: str = "") -> Optional[dict]:
    """住所のみの軽量取得（プレビュー初期表示用）。"""
    g = _geocode(name, hint)
    if g and g.get("address"):
        return {"address": g["address"], "lat": g.get("lat"), "lon": g.get("lon")}
    return None


def enrich(name: str, hint: str = "") -> dict:
    """住所・アクセス・開業・業種をまとめて機械補完（取れた項目のみ）。"""
    g = _geocode(name, hint)
    if not g:
        return {}
    out = {
        "address": g.get("address"),
        "open_year": g.get("open_year"),
        "category": g.get("category"),
    }
    if g.get("lat") and g.get("lon"):
        try:
            st = _nearest_station(float(g["lat"]), float(g["lon"]))
        except Exception:
            st = None
        if st:
            out["access"] = f"{st[0]} 徒歩約{st[1]}分"
    return {k: v for k, v in out.items() if v}
